"""The engine loop: pausing shows the no-game look and stops the derived signals' clocks."""
import unittest

from odradek_sync.engine import SyncEngine
from odradek_sync.outputs import Output, summarize
from odradek_sync.signals import SignalMap, SignalPipeline


class Session:
    """Attached from the start; `script(tick)` gives (animation states, paused) for each tick."""

    def __init__(self, script):
        self.script, self.tick, self.attached, self.memory = script, 0, True, object()

    def read(self):
        states, self.paused = self.script(self.tick)
        self.tick += 1
        return states

    def detach(self):
        pass


class Collect(Output):
    def __init__(self):
        self.seen = []

    def update(self, now, signals, states):
        self.seen.append(signals)


class PauseTest(unittest.TestCase):
    def run_engine(self, script, ticks):
        smap = SignalMap.from_dict({
            "signals": {"detected": {"animations": ["surprise"]}},
            "derived": [{"kind": "latch", "active": "held", "set": ["detected"], "max_seconds": 0.3}],
        })
        out = Collect()
        session = Session(script)
        SyncEngine(session, SignalPipeline(smap), [out], fps=100, log=lambda m: None).run(
            should_stop=lambda: session.tick >= ticks)
        return out.seen

    def test_paused_game_shows_the_no_game_look(self):
        seen = self.run_engine(lambda i: ({"surprise": 2}, 3 <= i < 6), 9)
        self.assertEqual([summarize(s) for s in seen[1:9]], ["-", "-", "paused", "paused", "paused", "-", "-", "-"])
        self.assertTrue(seen[4]["no_game"])

    def test_derived_timers_stop_while_paused(self):
        # held for 0.3 s of game time after the surprise; a 0.6 s pause in between doesn't use it up
        seen = self.run_engine(lambda i: ({"surprise": 3 if i < 3 else 2}, 5 <= i < 65), 70)
        self.assertTrue(seen[-1]["held"])


if __name__ == "__main__":
    unittest.main()
