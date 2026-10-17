"""Device geometry: where each LED sits, plus named regions. Built by layout strategies.

Effects never deal with a specific keyboard. They get a `Geometry` with LED positions in key units
(x = column, y = row, top-left is 0,0) and named regions ("all", "top_row", ...). A
`LayoutStrategy` turns a device description into a Geometry; `LayoutFactory` picks the first
strategy that supports the device, so new device shapes only need a new strategy.

Built-in strategies, tried in this order:
  MatrixLayout          the device reports a key matrix (most keyboards in OpenRGB): exact
  NamedKeyLayout        keyboard without a matrix whose LED names are keys ("Key: Escape"):
                        guess the size (60/65/75/TKL/full) and place keys on a reference layout
  EstimatedKeyboardLayout  keyboard with unusable LED names: guess the size from the LED count,
                        lay LEDs out in reading order (approximate)
  LinearLayout          anything else (strips, mice): one row
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from . import keyboard_layouts as kl
from .device import DeviceInfo


@dataclass
class Geometry:
    positions: list[tuple[float, float] | None]   # per LED; None = position unknown
    width: float
    height: float
    regions: dict[str, set[int]] = field(default_factory=dict)
    description: str = ""                          # how the layout was obtained, for users
    strategy: str = ""                             # name of the LayoutStrategy that built it

    @property
    def n(self) -> int:
        return len(self.positions)

    def region(self, name: str) -> set[int]:
        if name not in self.regions:
            raise KeyError(f"unknown region {name!r}; have: {', '.join(self.regions)}")
        return self.regions[name]

    def point(self, where: str) -> tuple[float, float]:
        """Named anchor points used by effects (e.g. a shockwave's origin)."""
        cx, cy = (self.width - 1) / 2, (self.height - 1) / 2
        return {"center": (cx, cy), "bottom_center": (cx, self.height - 1), "top_center": (cx, 0.0),
                "left_center": (0.0, cy), "right_center": (self.width - 1, cy)}[where]


def make_geometry(info: DeviceInfo, pos: list[tuple[float, float] | None], description: str) -> Geometry:
    """Geometry with the standard regions, derived from positions and key names.

    Regions: all, top_row / bottom_row (the highest / lowest row that has keys, so a 60% board's
    top row is its number row), left_half, right_half, and, where the keys exist: frow,
    number_row, arrows, wasd, numpad.
    """
    placed = [i for i, p in enumerate(pos) if p]
    if not placed:
        return Geometry(pos, 1.0, 1.0, {"all": set(range(info.led_count)), "top_row": set(), "bottom_row": set()},
                        description)
    xs, ys = [pos[i][0] for i in placed], [pos[i][1] for i in placed]
    top, bottom, mid = min(ys), max(ys), (min(xs) + max(xs)) / 2
    regions = {
        "all": set(range(info.led_count)),
        "top_row": {i for i in placed if pos[i][1] == top},
        "bottom_row": {i for i in placed if pos[i][1] == bottom},
        "left_half": {i for i in placed if pos[i][0] < mid},
        "right_half": {i for i in placed if pos[i][0] >= mid},
    }
    keys = {l.index: kl.canonical(l.name) for l in info.leds}
    groups = {"frow": kl.FROW, "number_row": {"`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "="},
              "arrows": kl.ARROWS, "wasd": {"w", "a", "s", "d"}, "numpad": kl.NUMPAD}
    for name, members in groups.items():
        idx = {i for i, k in keys.items() if k in members}
        if idx:
            regions[name] = idx
    return Geometry(pos, max(xs) + 1, bottom + 1, regions, description)


class LayoutStrategy(ABC):
    @abstractmethod
    def supports(self, info: DeviceInfo) -> bool: ...

    @abstractmethod
    def build(self, info: DeviceInfo) -> Geometry: ...


class MatrixLayout(LayoutStrategy):
    """Keyboards that report a row/column matrix (OpenRGB does for most keyboards)."""

    def supports(self, info: DeviceInfo) -> bool:
        return bool(info.matrix)

    def build(self, info: DeviceInfo) -> Geometry:
        pos: list[tuple[float, float] | None] = [None] * info.led_count
        for r, row in enumerate(info.matrix):
            for c, i in enumerate(row):
                if i is not None and i < info.led_count:
                    pos[i] = (float(c), float(r))
        return make_geometry(info, pos, f"key matrix {len(info.matrix)}x{len(info.matrix[0])} from the device")


def _is_keyboard(info: DeviceInfo) -> bool:
    return info.kind == "keyboard"


class NamedKeyLayout(LayoutStrategy):
    """Keyboard without a matrix, but its LED names are keys: place them on a reference layout.

    Used when at least `min_known` of the LEDs are recognisable keys. The size class comes from
    which keys exist (F-row? arrows? nav cluster? number pad?).
    """

    def __init__(self, min_known: float = 0.6):
        self.min_known = min_known

    def _known(self, info: DeviceInfo) -> dict[int, str]:
        return {l.index: k for l in info.leds if (k := kl.canonical(l.name))}

    def supports(self, info: DeviceInfo) -> bool:
        return _is_keyboard(info) and info.led_count > 0 and len(self._known(info)) >= self.min_known * info.led_count

    def build(self, info: DeviceInfo) -> Geometry:
        known = self._known(info)
        present = set(known.values())
        size = kl.classify_by_keys(present)
        tpl = kl.template(size, present)
        pos = [tpl.get(known.get(i, "")) for i in range(info.led_count)]
        unplaced = sum(p is None for p in pos)
        note = f", {unplaced} LEDs not placed (not keys, e.g. logo or light bar)" if unplaced else ""
        return make_geometry(info, pos, f"estimated {kl.SIZE_LABEL[size]} layout from key names{note}")


class EstimatedKeyboardLayout(LayoutStrategy):
    """Keyboard whose LED names aren't usable: size from the LED count, LEDs in reading order.

    Approximate. Effects still look sensible (top/bottom, left/right, rings), but individual
    keys may be off. A device file or a backend that reports the matrix fixes it.
    """

    def supports(self, info: DeviceInfo) -> bool:
        return _is_keyboard(info) and info.led_count > 0

    def build(self, info: DeviceInfo) -> Geometry:
        size = kl.classify_by_count(info.led_count)
        slots = sorted(kl.template(size).values(), key=lambda p: (p[1], p[0]))
        pos = [slots[i] if i < len(slots) else None for i in range(info.led_count)]
        return make_geometry(info, pos, f"estimated {kl.SIZE_LABEL[size]} layout from the LED count "
                                        f"({info.led_count}); key positions are approximate")


class LinearLayout(LayoutStrategy):
    """Fallback: LEDs in a single row (strips, mice, anything that isn't a keyboard)."""

    def supports(self, info: DeviceInfo) -> bool:
        return True

    def build(self, info: DeviceInfo) -> Geometry:
        n = info.led_count
        return Geometry([(float(i), 0.0) for i in range(n)], float(max(n, 1)), 1.0,
                        {"all": set(range(n)), "top_row": set(range(n)), "bottom_row": set(range(n))},
                        f"{n} LEDs in a row")


class LayoutFactory:
    def __init__(self, strategies: list[LayoutStrategy] | None = None):
        self.strategies = strategies or [MatrixLayout(), NamedKeyLayout(), EstimatedKeyboardLayout(), LinearLayout()]

    def register(self, strategy: LayoutStrategy) -> None:
        """Add a strategy that takes precedence over the built-in ones."""
        self.strategies.insert(0, strategy)

    def build(self, info: DeviceInfo, overrides: list[dict] | None = None) -> Geometry:
        strategy = next(s for s in self.strategies if s.supports(info))
        g = strategy.build(info)
        g.strategy = type(strategy).__name__
        for o in overrides or []:
            if o.get("device", {}).get("match", "\0").lower() in info.name.lower():
                apply_regions(g, info, o.get("regions", {}))
                g.description += f"; regions from config/devices ({o['device']['match']})"
        return g


def apply_regions(g: Geometry, info: DeviceInfo, regions: dict) -> None:
    """Device-specific regions from config/devices/*.toml: {"rows": [...]} or {"keys": [...]}."""
    by_name: dict[str, int] = {}
    for l in info.leds:
        by_name[l.name.lower()] = l.index
        if (c := kl.canonical(l.name)):
            by_name.setdefault(c, l.index)
    for name, spec in regions.items():
        idx: set[int] = set()
        for r in spec.get("rows", []):
            idx |= {i for i, p in enumerate(g.positions) if p and p[1] == r}
        for k in spec.get("keys", []):
            i = by_name.get(k.lower(), by_name.get(kl.canonical(k) or "\0"))
            if i is not None:
                idx.add(i)
        g.regions[name] = idx
