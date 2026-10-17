"""Effect base class, registry and factory.

An effect turns time (and the current signals) into one colour per LED. Effects are created by
name from config through `create_effect(name, params)`. Register new ones with
`@register_effect("my_effect")`; parameters come straight from the TOML `params` table.
"""
from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ...config import ConfigError
from ...util import BLACK, Color, parse_color
from ..geometry import Geometry

_EFFECTS: dict[str, type["Effect"]] = {}


def register_effect(name: str):
    def deco(cls):
        cls.effect_name = name
        _EFFECTS[name] = cls
        return cls
    return deco


def create_effect(name: str, params: dict | None = None) -> "Effect":
    if name not in _EFFECTS:
        raise ConfigError(f"unknown effect {name!r}; known: {', '.join(sorted(_EFFECTS))}")
    return _EFFECTS[name](**(params or {}))


def available_effects() -> dict[str, str]:
    return {n: " ".join((c.__doc__ or "").split()) for n, c in sorted(_EFFECTS.items())}


@dataclass
class FrameContext:
    geometry: Geometry
    now: float
    signals: dict = field(default_factory=dict)
    rises: dict[str, float] = field(default_factory=dict)   # last rising edge per boolean signal


class Effect(ABC):
    effect_name = "?"

    def __init__(self, **params):
        self.params = params
        self.t0 = 0.0
        self.state: dict = {}
        self.setup()

    # helpers for subclasses
    def p(self, key: str, default):
        return self.params.get(key, default)

    def color(self, key: str = "color", default="#ffffff") -> Color:
        try:
            return parse_color(self.p(key, default))
        except (ValueError, TypeError) as e:
            raise ConfigError(f"{self.effect_name}.{key}: {e}") from e

    @staticmethod
    def dist(p: tuple[float, float], o: tuple[float, float], y_scale: float = 1.0) -> float:
        return math.hypot(p[0] - o[0], (p[1] - o[1]) * y_scale)

    def setup(self) -> None:
        """Parse params (called once)."""

    def start(self, now: float) -> None:
        """Called when the effect becomes active; resets its clock and state."""
        self.t0, self.state = now, {}

    def frame(self, ctx: FrameContext) -> list[Color]:
        return self.render(ctx.now - self.t0, ctx)

    @abstractmethod
    def render(self, t: float, ctx: FrameContext) -> list[Color]:
        """One colour per LED for time t (seconds since start). LEDs without a position may be BLACK."""

    def each(self, ctx: FrameContext, fn) -> list[Color]:
        """Map fn(index, position) over LEDs, BLACK where the position is unknown."""
        return [BLACK if p is None else fn(i, p) for i, p in enumerate(ctx.geometry.positions)]
