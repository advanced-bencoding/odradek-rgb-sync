"""Labelled captures of all animation states, and a comparison that finds state-specific animations.

Capture each in-game state a few times (`recon capture blue`, `recon capture orange`, ...). An
animation is a candidate for a state when its value is steady within every capture of each label
and differs between labels.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ..game import StateReader

VARIES = -1


class CaptureStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def add(self, reader: StateReader, label: str, seconds: float = 2.0, hz: float = 30) -> dict:
        """Sample for `seconds`; animations that change during the window are stored as VARIES."""
        steady: dict[str, int] = {}
        end = time.time() + seconds
        while True:
            states = reader.read()
            if states is None:
                raise RuntimeError("couldn't read game memory")
            for k, v in states.items():
                steady[k] = v if steady.get(k, v) == v else VARIES
            if time.time() >= end:
                break
            time.sleep(1 / hz)
        cap = {"label": label, "t": time.time(), "states": steady}
        caps = self.load() + [cap]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(caps), encoding="utf-8")
        return cap

    def reset(self) -> None:
        self.path.unlink(missing_ok=True)

    def compare(self) -> list[tuple[str, dict[str, int]]]:
        """[(animation, {label: value})] for animations that tell the labels apart."""
        caps = self.load()
        labels = sorted({c["label"] for c in caps})
        if len(labels) < 2:
            return []
        names = set().union(*(c["states"] for c in caps))
        out = []
        for n in sorted(names):
            per: dict[str, int] = {}
            ok = True
            for c in caps:
                v = c["states"].get(n, VARIES)
                if v == VARIES or per.setdefault(c["label"], v) != v:
                    ok = False
                    break
            if ok and len(set(per.values())) > 1:
                out.append((n, per))
        return out
