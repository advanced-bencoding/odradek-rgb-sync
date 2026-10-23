"""The effect map (signals -> effects, as data) and the compositor that renders it.

An effect map (config/effects/*.toml) is a stack of layers, drawn bottom to top:

  kind = "state"    the first rule whose `when` conditions all hold is shown (top rule wins)
  kind = "trigger"  a rule plays once for `duration` seconds when its `on` signal turns on

Each layer covers a `region` of the device ("all", "top_row", or one defined per device) and
blends onto the layers below with "replace", "max" or "add". Conditions are strings:
"signal" (truthy), "!signal" (falsy), "signal=value", "signal!=value". The effect name "none"
makes the layer transparent while that rule holds.

An optional [accessibility] table (max_brightness, smoothing) runs every frame through a
`Softener`, which caps brightness and turns hard steps into fades (see config/effects/subtle.toml).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..config import ConfigError
from ..util import BLACK, RGB, Color, to_rgb
from .effects import Effect, FrameContext, create_effect
from .geometry import Geometry

BLENDS = ("replace", "max", "add")


@dataclass(frozen=True)
class Condition:
    signal: str
    op: str            # truthy | falsy | eq | ne
    value: str | None = None

    @classmethod
    def parse(cls, s: str) -> "Condition":
        s = s.strip()
        if "!=" in s:
            k, v = s.split("!=", 1)
            return cls(k.strip(), "ne", v.strip())
        if "=" in s:
            k, v = s.split("=", 1)
            return cls(k.strip(), "eq", v.strip())
        if s.startswith("!"):
            return cls(s[1:].strip(), "falsy")
        return cls(s, "truthy")

    def holds(self, signals: dict) -> bool:
        v = signals.get(self.signal)
        if self.op == "truthy":
            return bool(v)
        if self.op == "falsy":
            return not v
        same = str(v).lower() == str(self.value).lower()
        return same if self.op == "eq" else not same


@dataclass
class Rule:
    effect_name: str
    params: dict
    when: list[Condition] = field(default_factory=list)
    on: str | None = None
    duration: float = 1.0
    effect: Effect | None = None

    @property
    def label(self) -> str:
        cond = self.on or " & ".join(f"{'!' if c.op == 'falsy' else ''}{c.signal}"
                                     f"{'=' + c.value if c.op == 'eq' else '!=' + c.value if c.op == 'ne' else ''}"
                                     for c in self.when) or "default"
        return f"{cond} -> {self.effect_name}"


@dataclass
class Layer:
    name: str
    kind: str
    region: str
    blend: str
    rules: list[Rule]
    active: Rule | None = None
    until: float = 0.0


@dataclass
class EffectMap:
    name: str
    fps: float
    layers: list[dict]
    demos: list[dict]
    accessibility: "Softener | None" = None

    @classmethod
    def from_dict(cls, d: dict) -> "EffectMap":
        a = d.get("accessibility")
        soft = Softener(float(a.get("max_brightness", 1.0)), float(a.get("smoothing", 0.0))) if a else None
        em = cls(d.get("name", "?"), float(d.get("fps", 30)), list(d.get("layer", [])), list(d.get("demo", [])), soft)
        em.build_layers()  # validate early: unknown effects, kinds, blends
        return em

    def build_layers(self) -> list[Layer]:
        layers = []
        for ld in self.layers:
            kind, blend = ld.get("kind", "state"), ld.get("blend", "replace")
            if kind not in ("state", "trigger"):
                raise ConfigError(f"layer {ld.get('name')}: kind must be state or trigger")
            if blend not in BLENDS:
                raise ConfigError(f"layer {ld.get('name')}: blend must be one of {BLENDS}")
            rules = []
            for rd in ld.get("rule", []):
                when = rd.get("when", [])
                when = [when] if isinstance(when, str) else when
                name = rd["effect"]
                rule = Rule(name, dict(rd.get("params", {})), [Condition.parse(w) for w in when],
                            rd.get("on"), float(rd.get("duration", 1.0)))
                if kind == "trigger" and not rule.on:
                    raise ConfigError(f"layer {ld.get('name')}: trigger rules need `on`")
                rule.effect = None if name == "none" else create_effect(name, rule.params)
                rules.append(rule)
            layers.append(Layer(ld.get("name", f"layer{len(layers)}"), kind, ld.get("region", "all"), blend, rules))
        return layers

    def referenced_signals(self) -> set[str]:
        out = set()
        for ld in self.layers:
            for rd in ld.get("rule", []):
                when = rd.get("when", [])
                for w in [when] if isinstance(when, str) else when:
                    out.add(Condition.parse(w).signal)
                if rd.get("on"):
                    out.add(rd["on"])
                if "signal" in rd.get("params", {}):
                    out.add(rd["params"]["signal"])
        return out


class Softener:
    """Accessibility filter applied to every finished frame, whatever the effects do.

    - max_brightness (0..1): no LED channel goes above this share of full brightness.
    - smoothing (seconds): each LED eases toward its target with this time constant, so on/off
      steps become gentle fades. 0.25 s keeps even a hard strobe well under WCAG 2.3.1's limit
      of three flashes per second.
    """

    def __init__(self, max_brightness: float = 1.0, smoothing: float = 0.0):
        if not 0 < max_brightness <= 1:
            raise ConfigError("accessibility.max_brightness must be in (0, 1]")
        if smoothing < 0:
            raise ConfigError("accessibility.smoothing must be >= 0")
        self.cap, self.tau = 255 * max_brightness, smoothing
        self.prev: list[Color] | None = None
        self.t: float | None = None

    def apply(self, now: float, frame: list[Color]) -> list[Color]:
        capped = []
        for c in frame:
            m = max(c)
            capped.append(c if m <= self.cap else (c[0] * self.cap / m, c[1] * self.cap / m, c[2] * self.cap / m))
        if self.tau > 0 and self.prev is not None and len(self.prev) == len(capped):
            k = 1 - math.exp(-max(0.0, now - self.t) / self.tau)
            capped = [(p[0] + (c[0] - p[0]) * k, p[1] + (c[1] - p[1]) * k, p[2] + (c[2] - p[2]) * k)
                      for p, c in zip(self.prev, capped)]
        self.prev, self.t = capped, now
        return capped


class Compositor:
    def __init__(self, effect_map: EffectMap, geometry: Geometry):
        self.geometry = geometry
        self.softener = (Softener(effect_map.accessibility.cap / 255, effect_map.accessibility.tau)
                         if effect_map.accessibility else None)
        self.layers = effect_map.build_layers()
        for layer in self.layers:
            geometry.region(layer.region)  # fail early on unknown regions
        self.prev: dict = {}
        self.rises: dict[str, float] = {}

    def frame(self, now: float, signals: dict) -> list[RGB]:
        for k, v in signals.items():
            if v and not self.prev.get(k):
                self.rises[k] = now
        ctx = FrameContext(self.geometry, now, signals, self.rises)
        out: list[Color] = [BLACK] * self.geometry.n
        for layer in self.layers:
            rule = self._select(layer, now, signals)
            if rule is None or rule.effect is None:
                continue
            colours = rule.effect.frame(ctx)
            for i in self.geometry.region(layer.region):
                c = colours[i]
                if layer.blend == "replace":
                    out[i] = c
                elif layer.blend == "max":
                    o = out[i]
                    out[i] = (max(o[0], c[0]), max(o[1], c[1]), max(o[2], c[2]))
                else:
                    o = out[i]
                    out[i] = (o[0] + c[0], o[1] + c[1], o[2] + c[2])
        self.prev = dict(signals)
        if self.softener:
            out = self.softener.apply(now, out)
        return [to_rgb(c) for c in out]

    def _select(self, layer: Layer, now: float, signals: dict) -> Rule | None:
        if layer.kind == "trigger":
            for rule in layer.rules:
                if self.rises.get(rule.on) == now:
                    layer.active, layer.until = rule, now + rule.duration
                    if rule.effect:
                        rule.effect.start(now)
                    break
            if layer.active and now > layer.until:
                layer.active = None
            return layer.active
        rule = next((r for r in layer.rules if all(c.holds(signals) for c in r.when)), None)
        if rule is not layer.active:
            layer.active = rule
            if rule and rule.effect:
                rule.effect.start(now)
        return rule

    def check_firmware(self) -> None:
        """Fail early if a rule can't run on a firmware-mode device (see device.FirmwareModeDevice)."""
        for layer in self.layers:
            if not self.geometry.region(layer.region):
                continue
            for rule in layer.rules:
                if rule.effect is not None and rule.effect.firmware_mode is None:
                    raise ConfigError(f"layer {layer.name}: the {rule.effect_name!r} effect can't run in this "
                                      "device's firmware; use `aura` effects (see config/effects/z13.toml)")

    def firmware_mode(self):
        """What a firmware-mode device shows after the last frame(): the top layer showing something wins
        outright (no blending in firmware). None = no layer is showing anything."""
        for layer in reversed(self.layers):
            rule = layer.active
            if rule is not None and rule.effect is not None and self.geometry.region(layer.region):
                return rule.effect.firmware_mode
        return None

    def describe(self) -> dict[str, str]:
        """Which rule each layer is showing (for status output)."""
        return {l.name: l.active.label for l in self.layers if l.active}
