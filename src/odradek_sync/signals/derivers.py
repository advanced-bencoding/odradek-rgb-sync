"""Derivers turn raw signals into richer ones over time (plug-ins, selected by `kind` in config).

Example: the blue warning light. Rapid pulsing holds its animation on; slower pulsing switches it
on for ~0.27 s at intervals that grow as BTs get further away. `pulse_rate` turns that blinking
raw signal into a steady "blue" plus a "blue_pulse" level (rapid / fast / slow).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from ..config import ConfigError

_DERIVERS: dict[str, Callable[[dict], "Deriver"]] = {}


def register_deriver(kind: str):
    def deco(cls):
        _DERIVERS[kind] = cls
        return cls
    return deco


def create_deriver(spec: dict) -> "Deriver":
    kind = spec.get("kind")
    if kind not in _DERIVERS:
        raise ConfigError(f"unknown deriver kind {kind!r}; known: {', '.join(_DERIVERS)}")
    return _DERIVERS[kind](spec)


class Deriver(ABC):
    def __init__(self, spec: dict):
        self.spec = spec

    @property
    @abstractmethod
    def outputs(self) -> list[str]:
        """Names of the signals this deriver writes."""

    @abstractmethod
    def update(self, now: float, signals: dict) -> None:
        """Read inputs from `signals` and write outputs into it."""


@register_deriver("pulse_rate")
class PulseRate(Deriver):
    """Blinking signal -> held "active" flag + pulse level.

    Config keys: source, active, level, cancel (list), hold (s), steady (s), slow_threshold (s).
    Level is "rapid" when the source stays on longer than `steady`; otherwise the median of the last
    three on-to-on intervals picks "fast" (< slow_threshold) or "slow"; None until known.
    """

    def __init__(self, spec: dict):
        super().__init__(spec)
        try:
            self.source = spec["source"]
        except KeyError as e:
            raise ConfigError("pulse_rate needs a 'source' signal") from e
        self.active = spec.get("active", f"{self.source}_active")
        self.level = spec.get("level", f"{self.source}_level")
        self.cancel = list(spec.get("cancel", []))
        self.hold = float(spec.get("hold", 4.5))
        self.steady = float(spec.get("steady", 1.0))
        self.slow_threshold = float(spec.get("slow_threshold", 2.5))
        self._reset()

    @property
    def outputs(self) -> list[str]:
        return [self.active, self.level]

    def _reset(self):
        self.prev, self.rise, self.fall, self.periods = False, None, None, []

    def update(self, now: float, signals: dict) -> None:
        on = bool(signals.get(self.source))
        if any(signals.get(c) for c in self.cancel):
            self._reset()
            signals[self.active], signals[self.level] = False, None
            return
        if on and not self.prev:
            if self.fall is not None and now - self.fall < self.hold and self.fall - self.rise < self.steady:
                self.periods = (self.periods + [now - self.rise])[-3:]
            self.rise = now
        if self.prev and not on:
            self.fall = now
        self.prev = on
        if on and now - self.rise > self.steady:
            self.periods = []
            active, level = True, "rapid"
        elif not on and (self.fall is None or now - self.fall > self.hold):
            self.periods = []
            active, level = False, None
        elif not self.periods:
            active, level = True, None
        else:
            median = sorted(self.periods)[len(self.periods) // 2]
            active, level = True, "slow" if median >= self.slow_threshold else "fast"
        signals[self.active], signals[self.level] = active, level
