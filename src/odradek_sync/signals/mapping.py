"""Signal maps: named, human-level signals defined by which animations are playing.

A signal map is data (config/signals/<game>.toml). Each signal is true while any of its animations
is in its play state (3 = playing unless the signal says otherwise).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import ConfigError

CONFIDENCE = ("confirmed", "likely", "weak")


@dataclass(frozen=True)
class SignalDef:
    name: str
    animations: tuple[str, ...]
    state: int = 3
    confidence: str = "weak"
    description: str = ""
    evidence: str = ""


@dataclass
class SignalMap:
    game: str
    signals: dict[str, SignalDef]
    derived: list[dict] = field(default_factory=list)
    unmapped: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SignalMap":
        sigs = {}
        for name, s in d.get("signals", {}).items():
            if s.get("confidence", "weak") not in CONFIDENCE:
                raise ConfigError(f"signal {name}: confidence must be one of {CONFIDENCE}")
            sigs[name] = SignalDef(name, tuple(s["animations"]), s.get("state", 3), s.get("confidence", "weak"),
                                   s.get("description", ""), s.get("evidence", ""))
        return cls(d.get("game", "?"), sigs, list(d.get("derived", [])), dict(d.get("unmapped", {})))

    @property
    def animations(self) -> set[str]:
        return {a for s in self.signals.values() for a in s.animations}

    def evaluate(self, states: dict[str, int]) -> dict[str, bool]:
        return {name: any(states.get(a) == s.state for a in s.animations) for name, s in self.signals.items()}
