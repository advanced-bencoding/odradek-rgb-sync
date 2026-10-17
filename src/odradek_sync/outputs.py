"""Outputs receive every tick's signals: lighting, console status, a JSONL recorder, ...

Add a new destination (MQTT, a serial device, a web socket) by implementing `Output`.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from pathlib import Path

from .lighting.compositor import Compositor
from .lighting.device import LightingDevice
from .signals import SignalPipeline
from .util import stamp


class Output(ABC):
    @abstractmethod
    def update(self, now: float, signals: dict, states: dict[str, int] | None) -> None: ...

    def close(self) -> None:
        pass


class LightingOutput(Output):
    def __init__(self, device: LightingDevice, compositor: Compositor):
        self.device, self.compositor = device, compositor

    def update(self, now, signals, states):
        self.device.show(self.compositor.frame(now, signals))

    def close(self):
        self.device.show(self.compositor.frame(time.time(), SignalPipeline.idle()))
        self.device.close()


def summarize(signals: dict) -> str:
    """'blue blue_pulse=fast bb_scared' - the truthy signals, compactly."""
    parts = [k if v is True else f"{k}={v}" for k, v in signals.items() if v and k != "no_game"]
    return "no game" if signals.get("no_game") else (" ".join(parts) or "-")


class StatusPrinter(Output):
    """Prints a line whenever the set of active signals (or the layers' chosen effects) changes."""

    def __init__(self, compositor: Compositor | None = None, show_effects: bool = False):
        self.compositor, self.show_effects, self.last = compositor, show_effects, None

    def update(self, now, signals, states):
        line = summarize(signals)
        if self.show_effects and self.compositor:
            line += "   [" + "; ".join(f"{k}: {v}" for k, v in self.compositor.describe().items()) + "]"
        if line != self.last:
            print(f"{stamp(now)}  {line}", flush=True)
            self.last = line


class Recorder(Output):
    """JSON lines: every animation state change and every signal change, timestamped."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(path, "a", encoding="utf-8")
        self.prev_states: dict[str, int] = {}
        self.prev_signals: dict | None = None

    def update(self, now, signals, states):
        t = round(now, 3)
        for k, v in (states or {}).items():
            if self.prev_states.get(k) != v:
                self.f.write(json.dumps({"t": t, "anim": k, "from": self.prev_states.get(k), "to": v}) + "\n")
        if states:
            self.prev_states = states
        if signals != self.prev_signals:
            self.f.write(json.dumps({"t": t, "signals": signals}) + "\n")
            self.prev_signals = dict(signals)
            self.f.flush()

    def close(self):
        self.f.close()
