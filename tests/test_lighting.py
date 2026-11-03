import importlib.util
import types
import unittest

from odradek_sync.lighting.compositor import Compositor, Condition, EffectMap, Softener
from odradek_sync.lighting.console_repository import ConsoleRepository
from odradek_sync.lighting.device import DeviceInfo, LedInfo, LightingDevice
from odradek_sync.outputs import LightingOutput
from odradek_sync.lighting.effects import available_effects, create_effect
from odradek_sync.lighting.effects.base import FrameContext
from odradek_sync.lighting.geometry import LayoutFactory

INFO = ConsoleRepository().info
RED, BLUE = "#ff0000", "#0000ff"

MAP = {
    "layer": [
        {"name": "base", "kind": "state", "rule": [
            {"when": ["orange"], "effect": "solid", "params": {"color": RED}},
            {"when": ["blue", "pulse=rapid"], "effect": "solid", "params": {"color": BLUE}},
            {"effect": "off"},
        ]},
        {"name": "events", "kind": "trigger", "blend": "max", "rule": [
            {"on": "scan", "effect": "solid", "duration": 1.0, "params": {"color": "#00ff00"}},
        ]},
        {"name": "top", "kind": "state", "region": "top_row", "rule": [
            {"when": ["bb"], "effect": "solid", "params": {"color": "#ffffff"}},
            {"effect": "none"},
        ]},
    ]
}


class GeometryTest(unittest.TestCase):
    def test_matrix_layout_regions(self):
        g = LayoutFactory().build(INFO)
        self.assertEqual(g.n, INFO.led_count)
        self.assertEqual((g.width, g.height), (15.0, 6.0))
        self.assertEqual(len(g.region("top_row")), 13)   # Esc + F1..F12

    def test_linear_fallback_and_overrides(self):
        strip = DeviceInfo("s", "Strip", "ledstrip", tuple(LedInfo(i, f"LED {i}") for i in range(10)))
        g = LayoutFactory().build(strip, [{"device": {"match": "strip"}, "regions": {"ends": {"keys": ["LED 0", "LED 9"]}}}])
        self.assertEqual(g.region("ends"), {0, 9})
        self.assertEqual(g.height, 1.0)


class CompositorTest(unittest.TestCase):
    def setUp(self):
        self.g = LayoutFactory().build(INFO)
        self.c = Compositor(EffectMap.from_dict(MAP), self.g)
        self.top = next(iter(self.g.region("top_row")))
        self.body = next(i for i in range(self.g.n) if i not in self.g.region("top_row"))

    def test_first_matching_rule_wins(self):
        f = self.c.frame(0.0, {"orange": True, "blue": True, "pulse": "rapid"})
        self.assertEqual(f[self.body], (255, 0, 0))
        f = self.c.frame(0.1, {"blue": True, "pulse": "rapid"})
        self.assertEqual(f[self.body], (0, 0, 255))
        f = self.c.frame(0.2, {"blue": True, "pulse": "fast"})
        self.assertEqual(f[self.body], (0, 0, 0))

    def test_trigger_plays_for_duration_and_blends_max(self):
        self.c.frame(0.0, {"orange": True})
        f = self.c.frame(0.1, {"orange": True, "scan": True})
        self.assertEqual(f[self.body], (255, 255, 0))
        f = self.c.frame(0.9, {"orange": True, "scan": True})
        self.assertEqual(f[self.body], (255, 255, 0))
        f = self.c.frame(1.2, {"orange": True, "scan": True})
        self.assertEqual(f[self.body], (255, 0, 0))

    def test_region_layer_and_transparent_none(self):
        f = self.c.frame(0.0, {"orange": True, "bb": True})
        self.assertEqual((f[self.top], f[self.body]), ((255, 255, 255), (255, 0, 0)))
        f = self.c.frame(0.1, {"orange": True})
        self.assertEqual(f[self.top], (255, 0, 0))

    def test_conditions(self):
        self.assertTrue(Condition.parse("!x").holds({}))
        self.assertTrue(Condition.parse("lvl=fast").holds({"lvl": "fast"}))
        self.assertTrue(Condition.parse("lvl!=fast").holds({"lvl": "slow"}))


class SoftenerTest(unittest.TestCase):
    def test_caps_brightness_keeping_hue(self):
        out = Softener(max_brightness=0.5).apply(0.0, [(255.0, 128.0, 0.0)])
        self.assertAlmostEqual(out[0][0], 127.5)
        self.assertAlmostEqual(out[0][1], 64.0)

    def test_tames_a_full_brightness_strobe(self):
        s, swing = Softener(max_brightness=1.0, smoothing=0.35), []
        for n in range(300):                       # 15 Hz on/off strobe at 30 fps for 10 s
            v = s.apply(n / 30, [(255.0, 255.0, 255.0) if n % 2 else (0.0, 0.0, 0.0)])[0][0]
            if n > 150:
                swing.append(v)
        self.assertLess(max(swing) - min(swing), 0.1 * 255)

    def test_subtle_map_enables_the_filter(self):
        from odradek_sync.config import ConfigLoader
        em = EffectMap.from_dict(ConfigLoader([]).load("effects", "subtle"))
        self.assertIsNotNone(em.accessibility)
        c = Compositor(em, LayoutFactory().build(INFO))
        frame = c.frame(0.0, {"blue": True, "blue_pulse": "rapid"})
        self.assertLessEqual(max(max(px) for px in frame), int(255 * 0.45))


@unittest.skipUnless(importlib.util.find_spec("openrgb"), "openrgb-python not installed")
class OpenRGBReleaseTest(unittest.TestCase):
    class Raw:
        """An openrgb-python device: its modes, the active one, and what was sent to it."""

        def __init__(self, modes, active):
            self.modes = [types.SimpleNamespace(name=n) for n in modes]
            self.active_mode, self.sent = modes.index(active), []

        def set_mode(self, mode):
            self.sent.append(mode.name)

        def set_colors(self, colors, fast=False):
            self.sent.append("colors")

    def device(self, modes, active, config=None):
        from odradek_sync.lighting.openrgb_repository import OpenRGBDevice
        raw = self.Raw(modes, active)
        d = OpenRGBDevice(raw, DeviceInfo("0", "AULA F75", "keyboard", ()))
        d.configure(config or {})
        return d, raw

    def test_aula_goes_off_without_a_game_and_direct_on_the_next_frame(self):
        d, raw = self.device(["Off", "Direct"], "Direct", {"openrgb": {"release_mode": "Off"}})
        self.assertTrue(d.release())
        self.assertTrue(d.release())                 # already handed back: nothing sent again
        d.show([(0, 0, 0)])
        d.show([(0, 0, 0)])
        self.assertTrue(d.release())
        self.assertEqual(raw.sent, ["Off", "Direct", "colors", "colors", "Off"])

    def test_without_a_release_mode_it_gives_back_the_mode_it_found(self):
        d, raw = self.device(["Static", "Wave", "Direct"], "Wave")
        d.show([(0, 0, 0)])
        self.assertTrue(d.release())
        self.assertEqual(raw.sent, ["Direct", "colors", "Wave"])
        self.assertFalse(self.device(["Static", "Direct"], "Direct")[0].release())   # nothing to give back

    def test_a_release_mode_the_device_lacks_is_an_error(self):
        from odradek_sync.lighting import DeviceError
        with self.assertRaises(DeviceError):
            self.device(["Off", "Direct"], "Direct", {"openrgb": {"release_mode": "Rainbow"}})


class OutputReleaseTest(unittest.TestCase):
    def test_lighting_output_releases_without_a_game(self):
        class Dev(LightingDevice):
            def __init__(self, can_release):
                self.info, self.can, self.log = INFO, can_release, []

            def show(self, colors):
                self.log.append("frame")

            def release(self):
                self.log.append("release")
                return self.can

        g = LayoutFactory().build(INFO)
        for can, want in ((True, ["release", "frame", "frame", "release"]),
                          (False, ["release", "frame", "frame", "frame", "release", "frame"])):
            dev = Dev(can)
            out = LightingOutput(dev, Compositor(EffectMap.from_dict(MAP), g))
            out.update(0.0, {"no_game": True}, None)
            out.update(0.1, {"orange": True}, {})
            out.update(0.2, {"no_game": True, "paused": True}, {})
            out.close()
            self.assertEqual(dev.log, want, f"can release: {can}")


class EffectsTest(unittest.TestCase):
    def test_every_builtin_renders_one_colour_per_led(self):
        g = LayoutFactory().build(INFO)
        for name in available_effects():
            e = create_effect(name)
            e.start(0.0)
            for t in (0.0, 0.5, 2.0):
                ctx = FrameContext(g, t, {}, {"blue_flash": 0.4})
                self.assertEqual(len(e.frame(ctx)), g.n, name)

    def test_radar_sweep_fades_into_its_background(self):
        g = LayoutFactory().build(INFO)
        e = create_effect("radar_sweep", {"color": RED, "background": BLUE, "floor": 0.5, "tail": 0.5})
        e.start(0.0)
        frame = e.frame(FrameContext(g, 0.0))
        self.assertIn((0.0, 0.0, 127.5), frame)            # away from the beam: the background at `floor`
        self.assertTrue(any(px[0] > 128 for px in frame))   # the beam itself

    def test_aura_mirrors_z13_firmware_modes(self):
        from odradek_sync.config import ConfigError
        g = LayoutFactory().build(INFO)

        def at(t, **params):
            e = create_effect("aura", params)
            e.start(0.0)
            frame = e.frame(FrameContext(g, t))
            self.assertEqual(len(set(frame)), 1)       # one zone: the whole board shares a colour
            return frame[0]
        self.assertEqual(at(0.0, mode="breathe", color=RED, color2=BLUE, period=4), (0.0, 0.0, 255.0))
        self.assertEqual(at(2.0, mode="breathe", color=RED, color2=BLUE, period=4), (255.0, 0.0, 0.0))
        self.assertEqual(at(0.6, mode="strobe", color=RED, period=1), (0.0, 0.0, 0.0))
        self.assertEqual(at(0.0, color=RED, brightness=1), (25.5, 0.0, 0.0))
        with self.assertRaises(ConfigError):
            create_effect("aura", {"color": "#000000"})  # the firmware picks its own colour for black


if __name__ == "__main__":
    unittest.main()
