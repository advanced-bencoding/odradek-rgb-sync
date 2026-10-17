"""Animation states -> signals: the mapping (data) plus derivers (code plug-ins)."""
from __future__ import annotations

from .derivers import Deriver, create_deriver, register_deriver
from .mapping import SignalDef, SignalMap


class SignalPipeline:
    """SignalMap.evaluate, then each deriver in order. Adds `no_game` (always False here)."""

    def __init__(self, signal_map: SignalMap):
        self.map = signal_map
        self.derivers = [create_deriver(d) for d in signal_map.derived]

    @property
    def signal_names(self) -> set[str]:
        return set(self.map.signals) | {o for d in self.derivers for o in d.outputs} | {"no_game"}

    def evaluate(self, now: float, states: dict[str, int]) -> dict:
        signals: dict = self.map.evaluate(states)
        for d in self.derivers:
            d.update(now, signals)
        signals["no_game"] = False
        return signals

    @staticmethod
    def idle() -> dict:
        """Signals while no game is attached."""
        return {"no_game": True}


__all__ = ["Deriver", "SignalDef", "SignalMap", "SignalPipeline", "create_deriver", "register_deriver"]
