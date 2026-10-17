import unittest

from odradek_sync.lighting import keyboard_layouts as kl
from odradek_sync.lighting.device import DeviceInfo, LedInfo
from odradek_sync.lighting.geometry import (EstimatedKeyboardLayout, LayoutFactory, LinearLayout, MatrixLayout,
                                            NamedKeyLayout)


def board(keys, kind="keyboard", matrix=None, extra=()):
    names = [f"Key: {k.title()}" for k in keys] + list(extra)
    return DeviceInfo("t", "Test board", kind, tuple(LedInfo(i, n) for i, n in enumerate(names)), matrix)


def strategy_for(info):
    return next(s for s in LayoutFactory().strategies if s.supports(info))


class CanonicalTest(unittest.TestCase):
    def test_openrgb_names_and_common_variants(self):
        cases = {"Key: Escape": "escape", "Esc": "escape", "Key: F7": "f7", "LCtrl": "left control",
                 "Right Ctrl": "right control", "R_Shift": "right shift", "PgUp": "page up",
                 "Numpad 7": "number pad 7", "KP Enter": "number pad enter", "Key: Number Pad .": "number pad .",
                 "Key: \\ (ANSI)": "\\ (ansi)", "Spacebar": "space", "Num Lock": "num lock", "Logo": None,
                 "LED 12": None}
        for name, want in cases.items():
            self.assertEqual(kl.canonical(name), want, name)


class SizeTest(unittest.TestCase):
    def test_classify_each_template_back_to_its_size(self):
        for size in kl.SIZES:
            keys = set(kl.template(size))
            self.assertEqual(kl.classify_by_keys(keys), size, size)

    def test_classify_by_count(self):
        self.assertEqual([kl.classify_by_count(n) for n in (61, 68, 84, 87, 104)], ["60", "65", "75", "tkl", "full"])


class NamedLayoutTest(unittest.TestCase):
    def test_75_percent_board(self):
        info = board(kl.template("75", {"delete", "page up", "page down", "end"}), extra=["Logo"])
        g = LayoutFactory().build(info)
        self.assertIn("75%", g.description)
        self.assertIn("1 LEDs not placed", g.description)
        names = {l.name: l.index for l in info.leds}
        self.assertIn(names["Key: Escape"], g.region("top_row"))
        self.assertIn(names["Key: Space"], g.region("bottom_row"))
        self.assertEqual(len(g.region("arrows")), 4)
        self.assertEqual(len(g.region("frow")), 12)

    def test_60_percent_top_row_is_the_number_row(self):
        info = board(kl.template("60", set()))
        g = LayoutFactory().build(info)
        self.assertIn("60%", g.description)
        top = {info.leds[i].name for i in g.region("top_row")}
        self.assertIn("Key: Escape", top)
        self.assertIn("Key: 1", top)
        self.assertNotIn("arrows", g.regions)

    def test_full_size_has_numpad_region(self):
        g = LayoutFactory().build(board(kl.template("full")))
        self.assertIn("full-size", g.description)
        self.assertEqual(len(g.region("numpad")), 17)


class FactoryTest(unittest.TestCase):
    def test_strategy_order(self):
        keys = list(kl.template("tkl"))
        self.assertIsInstance(strategy_for(board(keys, matrix=((0, 1),))), MatrixLayout)
        self.assertIsInstance(strategy_for(board(keys)), NamedKeyLayout)
        unnamed = DeviceInfo("u", "Mystery", "keyboard", tuple(LedInfo(i, f"LED {i}") for i in range(104)))
        self.assertIsInstance(strategy_for(unnamed), EstimatedKeyboardLayout)
        strip = DeviceInfo("s", "Strip", "ledstrip", tuple(LedInfo(i, f"LED {i}") for i in range(30)))
        self.assertIsInstance(strategy_for(strip), LinearLayout)

    def test_estimated_layout_places_every_key_led(self):
        unnamed = DeviceInfo("u", "Mystery", "keyboard", tuple(LedInfo(i, f"LED {i}") for i in range(104)))
        g = LayoutFactory().build(unnamed)
        self.assertIn("full-size", g.description)
        self.assertTrue(all(p is not None for p in g.positions))
        self.assertGreater(len(g.region("top_row")), 10)


if __name__ == "__main__":
    unittest.main()
