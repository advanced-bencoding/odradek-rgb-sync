import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from odradek_sync.app import keyboard as kbmod
from odradek_sync.app.keyboard import ResilientKeyboard
from odradek_sync.app.settings import Settings
from odradek_sync.app.tray import TrayState, menu_items
from odradek_sync.app.userlog import UserLog
from odradek_sync.config import ConfigLoader
from odradek_sync.lighting import BackendMissingError, DeviceRepository
from odradek_sync.lighting.compositor import EffectMap
from odradek_sync.lighting.console_repository import NullDevice


class Repo(DeviceRepository):
    """A backend with one keyboard. `fail` makes opening raise; `gate` makes it wait; `broken` devices can't show."""

    def __init__(self, name, fail=None, gate=None, broken=False):
        self.name, self.fail, self.gate, self.broken = name, fail, gate, broken
        self.opened, self.closed = [], 0

    def list_devices(self):
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail is not None:
            raise self.fail
        return [NullDevice().info]

    def open(self, selector=None):
        repo = self

        class Device(NullDevice):
            def show(self, colors):
                if repo.broken:
                    raise OSError("device stopped answering")
                super().show(colors)

            def close(self):
                repo.closed += 1
        self.opened.append(Device())
        return self.opened[-1]


class SwitchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = UserLog(Path(self.tmp.name) / "k.log")
        self.em = EffectMap.from_dict(ConfigLoader([]).load("effects", "default"))
        self.outcomes = []
        self.old = Repo("openrgb")
        self.kb = ResilientKeyboard(self.log, self.em, [], repo=self.old, backend="openrgb",
                                    on_backend=lambda b, changed: self.outcomes.append((b, changed)))
        self.kb.update(0.0, {"no_game": True}, None)
        self.assertIsNotNone(self.kb.device)

    def tearDown(self):
        self.log.close()
        self.tmp.cleanup()

    def lines(self):
        return [l.split("  ", 1)[1] for l in (Path(self.tmp.name) / "k.log").read_text(encoding="utf-8").splitlines()]

    def finish(self, now):
        self.kb.switching.done.wait(5)
        self.kb.update(now, {"no_game": True}, None)

    def test_switch_swaps_in_a_working_backend_live(self):
        new = Repo("z13")
        self.assertTrue(self.kb.switch("z13", new))
        self.assertFalse(self.kb.switch("z13", new))            # one switch at a time
        self.finish(1.0)
        self.assertEqual((self.kb.backend, self.kb.repo), ("z13", new))
        self.assertIs(self.kb.device, new.opened[0])
        self.assertIsNotNone(new.opened[0].last)                # it's showing frames
        self.assertEqual(self.old.closed, 1)                    # the old keyboard was let go
        self.assertEqual(self.outcomes, [("z13", True)])
        self.assertIn("Switched lighting to ASUS ROG Flow Z13 (z13ctl)", self.lines())

    def test_failed_switch_keeps_the_previous_backend(self):
        device = self.kb.device
        self.kb.switch("z13", Repo("z13", fail=BackendMissingError("x")))
        self.finish(1.0)
        self.assertEqual((self.kb.backend, self.kb.device), ("openrgb", device))
        self.assertEqual(self.outcomes, [("openrgb", False)])
        self.assertTrue(self.lines()[-1].startswith("Couldn't switch lighting to ASUS ROG Flow Z13 (z13ctl): "
                                                    "Lighting software is not installed. Staying with OpenRGB."))

    def test_a_backend_that_fails_right_after_switching_is_reverted(self):
        new = Repo("z13", broken=True)
        self.kb.switch("z13", new)
        new.broken = False
        self.finish(1.0)
        self.assertEqual(self.kb.backend, "z13")
        new.broken = True                                       # fails within the grace period
        self.kb.update(2.0, {"no_game": True}, None)
        self.kb.update(2.1, {"no_game": True}, None)            # reconnects to the previous one
        self.assertEqual((self.kb.backend, self.kb.repo), ("openrgb", self.old))
        self.assertIs(self.kb.device, self.old.opened[-1])
        self.assertEqual(self.outcomes, [("z13", True), ("openrgb", True)])
        self.assertIn("Going back to OpenRGB", self.lines()[-2])

    def test_after_the_grace_period_failures_are_ordinary_reconnects(self):
        new = Repo("z13")
        self.kb.switch("z13", new)
        self.finish(1.0)
        new.broken = True
        self.kb.update(1.0 + kbmod.SWITCH_GRACE + 1, {"no_game": True}, None)
        self.assertEqual(self.kb.backend, "z13")
        self.assertEqual(self.outcomes, [("z13", True)])

    def test_a_switch_that_hangs_times_out_and_is_cleaned_up(self):
        gate = threading.Event()
        new = Repo("z13", gate=gate)
        self.kb.switch("z13", new)
        sw = self.kb.switching
        self.kb.update(sw.started + kbmod.SWITCH_TIMEOUT + 1, {"no_game": True}, None)
        self.assertIsNone(self.kb.switching)
        self.assertEqual(self.outcomes, [("openrgb", False)])
        gate.set()                                              # it opens after all: closed, not used
        sw.done.wait(5)
        for _ in range(100):
            if new.closed:
                break
            threading.Event().wait(0.01)
        self.assertEqual(new.closed, 1)
        self.assertEqual(self.kb.backend, "openrgb")


class LightingChoiceTest(unittest.TestCase):
    def test_tray_greys_out_backends_that_cant_be_used(self):
        state = TrayState(lighting="openrgb", backends=(("openrgb", "OpenRGB", None),
                                                         ("z13", "ASUS ROG Flow Z13 (z13ctl)", "no Z13 found")))
        items = {m.action: m for m in menu_items(state) if m.action}
        self.assertTrue(items["lighting:openrgb"].checked and items["lighting:openrgb"].enabled)
        z13 = items["lighting:z13"]
        self.assertEqual((z13.checked, z13.enabled, z13.radio), (False, False, True))
        self.assertEqual(z13.label, "Lighting: ASUS ROG Flow Z13 (z13ctl) (no Z13 found)")
        self.assertEqual(len({m.id for m in menu_items(state)}), len(menu_items(state)))

    def test_sni_shows_lighting_entries_as_radio_buttons(self):
        try:
            from odradek_sync.app.tray import sni
        except ImportError:
            self.skipTest("jeepney not installed")
        state = TrayState(lighting="z13", backends=(("z13", "Z13", None),))
        props = sni.item_props(next(m for m in menu_items(state) if m.action == "lighting:z13"))
        self.assertEqual((props["toggle-type"], props["toggle-state"]), (("s", "radio"), ("i", 1)))

    def test_settings_remember_the_lighting_choice(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.toml"
            self.assertEqual(Settings.load(path)[0].lighting, "auto")
            Settings(lighting="z13").save(path)
            self.assertEqual(Settings.load(path), (Settings(lighting="z13"), None))
            path.write_text('lighting = "razer"\n', encoding="utf-8")
            s, problem = Settings.load(path)
            self.assertEqual(s.lighting, "auto")
            self.assertIn("razer", problem)

    def test_startup_uses_the_saved_backend_only_if_it_can_be_used(self):
        from odradek_sync.app.main import choose_backend
        ok, no_z13 = {"openrgb": None, "z13": None}, {"openrgb": None, "z13": "no Z13 found"}
        with mock.patch("odradek_sync.app.main.detect_backend", return_value="openrgb"):
            self.assertEqual(choose_backend("z13", ok), ("z13", None))
            self.assertEqual(choose_backend("auto", ok), ("openrgb", None))
            backend, note = choose_backend("z13", no_z13)
            self.assertEqual(backend, "openrgb")
            self.assertIn("no Z13 found", note)
            backend, note = choose_backend("z13", {"openrgb": None, "z13": "Linux only"})   # a Windows machine
            self.assertEqual(backend, "openrgb")
            self.assertIn("Linux only", note)


if __name__ == "__main__":
    unittest.main()
