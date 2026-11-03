import unittest

from odradek_sync.config import ConfigLoader
from odradek_sync.signals import SignalMap, SignalPipeline
from odradek_sync.signals.derivers import Latch, PulseRate

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


class LatchTest(unittest.TestCase):
    SPEC = {"kind": "latch", "active": "tar", "set": ["detected"], "clear": ["blue", "orange"], "max_seconds": 60}

    def run_steps(self, steps):
        d, out = Latch(self.SPEC), []
        for t, s in steps:
            d.update(t, s)
            out.append(s["tar"])
        return out

    def test_holds_from_set_until_clear(self):
        self.assertEqual(self.run_steps([
            (0, {"orange": True}),
            (1, {"detected": True}),      # orange ends in the frame the BT detects Sam
            (3, {}),                      # the detection is over; still in the tar
            (20, {}),
            (25, {"blue": True}),         # escaped
            (26, {}),
        ]), [False, True, True, True, False, False])

    def test_set_wins_over_clear_in_the_same_frame(self):
        self.assertEqual(self.run_steps([(0, {"detected": True, "orange": True}), (1, {})]), [True, True])

    def test_gives_up_after_max_seconds(self):
        self.assertEqual(self.run_steps([(0, {"detected": True}), (59, {}), (61, {})]), [True, True, False])

    def test_unless_ignores_set(self):
        d = Latch({**self.SPEC, "unless": ["blue"], "clear": []})
        s = {"detected": True, "blue": True}
        d.update(0, s)
        self.assertFalse(s["tar"])


class ShippedSignalMapTest(unittest.TestCase):
    def test_caught_in_the_tar_like_the_recordings(self):
        """orange -> a BT detects Sam (surprise) -> in the tar, only pointing -> escaped to blue (2 recordings)."""
        p = SignalPipeline(SignalMap.from_dict(ConfigLoader([]).load("signals", "death_stranding_dc")))
        steps = [(0.0, ["odra_main_warrning_sign_near_lp"]),
                 (4.5, ["odra_main_surprise", "odra_arm_surprise"]),
                 (6.7, ["odra_main_point_lp", "bbydef_q_crying_st"]),
                 (30.0, ["odra_main_point_lp"]),
                 (31.0, ["odra_main_warrning_sign_lp"])]
        got = []
        for t, playing in steps:
            s = p.evaluate(t, {a: 3 for a in playing})
            got.append((s["orange"], s["bt_detected"], s["tar"]))
        self.assertEqual(got, [(True, False, False), (False, True, True), (False, False, True),
                               (False, False, True), (False, False, False)])

    def test_surprise_during_blue_is_not_the_tar(self):
        """Seen once live: the Odradek's surprise during rapid blue, with no orange before and no tar after."""
        p = SignalPipeline(SignalMap.from_dict(ConfigLoader([]).load("signals", "death_stranding_dc")))
        p.evaluate(0.0, {"odra_main_warrning_sign_lp": 3})
        s = p.evaluate(2.0, {"odra_main_warrning_sign_lp": 3, "odra_main_surprise": 3})
        self.assertTrue(s["blue"] and s["bt_detected"])
        self.assertFalse(s["tar"])


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
