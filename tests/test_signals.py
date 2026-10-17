import unittest

from odradek_sync.signals import SignalMap, SignalPipeline
from odradek_sync.signals.derivers import PulseRate

SPEC = {"kind": "pulse_rate", "source": "flash", "active": "blue", "level": "pulse", "cancel": ["orange"]}


def run_pattern(on_off, step=0.05, deriver=None, extra=None):
    """on_off(t) -> bool; returns [(t, blue, pulse)] whenever the output changes."""
    d = deriver or PulseRate(SPEC)
    out, last, t = [], None, 0.0
    while t < 20:
        s = {"flash": on_off(t), **(extra(t) if extra else {})}
        d.update(t, s)
        cur = (s["blue"], s["pulse"])
        if cur != last:
            out.append((round(t, 2), *cur))
            last = cur
        t += step
    return out


class PulseRateTest(unittest.TestCase):
    def test_held_on_is_rapid(self):
        self.assertEqual(run_pattern(lambda t: True)[-1][1:], (True, "rapid"))

    def test_flash_every_1_8s_is_fast(self):
        self.assertEqual(run_pattern(lambda t: t % 1.8 < 0.27)[-1][1:], (True, "fast"))

    def test_flash_every_3_3s_is_slow(self):
        self.assertEqual(run_pattern(lambda t: t % 3.3 < 0.27)[-1][1:], (True, "slow"))

    def test_stops_after_hold(self):
        res = run_pattern(lambda t: t < 5 and t % 1.8 < 0.27)
        self.assertEqual(res[-1][1:], (False, None))

    def test_orange_cancels(self):
        res = run_pattern(lambda t: True, extra=lambda t: {"orange": t > 10})
        self.assertEqual(res[-1][1:], (False, None))


class SignalMapTest(unittest.TestCase):
    def test_state_values_and_pipeline(self):
        smap = SignalMap.from_dict({
            "signals": {"folded": {"animations": ["sleep_lp"], "state": 4, "confidence": "confirmed"},
                        "flash": {"animations": ["warn_lp"], "confidence": "likely"}},
            "derived": [SPEC],
        })
        p = SignalPipeline(smap)
        s = p.evaluate(0.0, {"sleep_lp": 4, "warn_lp": 2})
        self.assertTrue(s["folded"])
        self.assertFalse(s["flash"])
        self.assertFalse(s["no_game"])
        self.assertIn("pulse", p.signal_names)


if __name__ == "__main__":
    unittest.main()
