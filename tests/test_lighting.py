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

        def __init__(self, modes, active, name="AULA F75"):
            self.name, self.modes = name, [types.SimpleNamespace(name=n) for n in modes]
            self.active_mode, self.sent = modes.index(active), []
            self.reported: int | None = None       # what OpenRGB will say on the next update(), if it changed

        def set_mode(self, mode):
            self.sent.append(mode.name)
            self.active_mode = self.modes.index(mode)

        def update(self):
            self.sent.append("update")
            if self.reported is not None:
                self.active_mode, self.reported = self.reported, None

        def set_colors(self, colors, fast=False):
            self.sent.append("colors")

    def device(self, modes, active, config=None, client=None):
        from odradek_sync.lighting.openrgb_repository import OpenRGBDevice
        raw = self.Raw(modes, active)
        if client is not None:
            client.devices = [raw]
        d = OpenRGBDevice(raw, DeviceInfo("0", "AULA F75", "keyboard", ()), client)
        self.warning = d.configure(config or {})
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

    def test_a_release_mode_the_device_lacks_falls_back_with_a_warning(self):
        # another OpenRGB version may name the modes differently: the keyboard must still work
        d, raw = self.device(["Off", "Direct"], "Direct", {"openrgb": {"release_mode": "Rainbow"}})
        self.assertIn("'Rainbow'", self.warning)
        self.assertIn("no-game look", self.warning)
        self.assertFalse(d.release())                # found in Direct: nothing to give back
        d, raw = self.device(["Wave", "Direct"], "Wave", {"openrgb": {"release_mode": "Rainbow"}})
        self.assertIn("wave mode", self.warning)
        d.show([(0, 0, 0)])
        self.assertTrue(d.release())
        self.assertEqual(raw.sent, ["Direct", "colors", "Wave"])
        self.device(["Off", "Direct"], "Direct", {"openrgb": {"release_mode": "off"}})
        self.assertIsNone(self.warning)

    def test_a_mode_changed_behind_its_back_is_noticed_at_the_next_sync(self):
        # OpenRGB puts the keyboard back in Direct when it detects it again: the knob would stay locked
        d, raw = self.device(["Off", "Direct"], "Direct", {"openrgb": {"release_mode": "Off"}})
        self.assertTrue(d.release())
        raw.reported = 1                             # re-detected: Direct again
        self.assertTrue(d.release())                 # not time to check yet: the cache says Off
        d._next_sync = 0
        self.assertTrue(d.release())
        self.assertTrue(d.release())                 # checked again only after sync_every
        self.assertEqual(raw.sent, ["Off", "update", "Off"])
        raw.reported, d._next_sync = 0, 0            # someone switched it to Off mid-game
        d.show([(0, 0, 0)])
        self.assertEqual(raw.sent[3:], ["update", "Direct", "colors"])

    def test_follows_the_device_when_openrgb_rebuilds_its_list(self):
        from odradek_sync.lighting import NoDeviceError
        client = types.SimpleNamespace()
        d, old = self.device(["Off", "Direct"], "Off", {"openrgb": {"release_mode": "Off"}}, client)
        new = self.Raw(["Off", "Direct"], "Direct")
        client.devices = [self.Raw(["Static", "Direct"], "Static", name="Mouse"), new]   # replugged
        d._next_sync = 0
        self.assertTrue(d.release())
        self.assertEqual(new.sent, ["Off"])
        d.show([(0, 0, 0)])
        self.assertEqual(new.sent, ["Off", "Direct", "colors"])
        client.devices, d._next_sync = [], 0           # unplugged for good
        with self.assertRaises(NoDeviceError):
            d.release()


class EffectsCommandReleaseTest(unittest.TestCase):
    """`effects demo` and `effects show` leave the keyboard the way quitting `run` does: its own lighting back."""

    class Dev(LightingDevice):
        def __init__(self):
            self.info, self.log = INFO, []

        def show(self, colors):
            if not self.log or self.log[-1] != "frame":
                self.log.append("frame")

        def release(self):
            self.log.append("release")
            return True

        def close(self):
            self.log.append("close")

    def run_cli(self, argv):
        from unittest import mock
        from odradek_sync import cli
        dev = self.Dev()
        open_lighting = lambda args, loader, em: (dev, Compositor(em, LayoutFactory().build(dev.info)))
        with mock.patch.object(cli, "open_lighting", open_lighting), mock.patch("builtins.print"):
            args = cli.build_parser().parse_args(argv)
            args.func(args)
        return dev.log

    def test_show_hands_the_keyboard_back(self):
        self.assertEqual(self.run_cli(["effects", "show", "solid", "--seconds", "0.05", "--lighting", "console"]),
                         ["frame", "release", "close"])

    def test_demo_hands_the_keyboard_back(self):
        self.assertEqual(self.run_cli(["effects", "demo", "--seconds", "0.05", "--lighting", "console", "--effects", "default", "Caught"]),
                         ["frame", "release", "close"])


class CrossEffectTest(unittest.TestCase):
    def test_a_plus_sign_through_the_middle(self):
        info = DeviceInfo("k", "Grid", "keyboard", tuple(LedInfo(i, f"K{i}") for i in range(5 * 7)),
                          tuple(tuple(r * 7 + c for c in range(7)) for r in range(5)))
        g = LayoutFactory().build(info)
        ctx = FrameContext(g, 0.0, {}, {})
        frame = create_effect("cross", {"color": "#ff0000", "background": "#0000ff", "floor": 0.5}).render(0.0, ctx)
        on = {i for i, c in enumerate(frame) if c == (255, 0, 0)}
        self.assertEqual(on, {r * 7 + 3 for r in range(5)} | {2 * 7 + c for c in range(7)})   # column 3, row 2
        self.assertTrue(all(c == (0, 0, 127.5) for i, c in enumerate(frame) if i not in on))   # background at floor

    def test_flashes_with_its_signal(self):
        g = LayoutFactory().build(INFO)
        cross = create_effect("cross", {"color": "#ff0000", "signal": "cross_flash", "dim": 0.2})
        mid = lambda now: max(max(c) for c in cross.render(now, FrameContext(g, now, {}, {"cross_flash": 10.0})))
        self.assertEqual(mid(5.0), 51)                   # before the flash: dim
        self.assertEqual(mid(10.22), 255)                # mid-flash: full
        self.assertEqual(mid(11.0), 51)                  # after it: dim again


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
