import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from odradek_sync.app.instance import SingleInstance
from odradek_sync.app.settings import Settings
from odradek_sync.app.userlog import UserLog
from odradek_sync.game import Attach


class AppPiecesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_settings_file_is_created_with_defaults_and_read_back(self):
        path = self.dir / "settings.toml"
        s, problem = Settings.load(path)
        self.assertEqual((s.subtle, s.autostart, s.keyboard, problem), (False, True, "", None))
        path.write_text(path.read_text(encoding="utf-8").replace("subtle = false", "subtle = true"), encoding="utf-8")
        self.assertTrue(Settings.load(path)[0].subtle)
        path.write_text("subtle = [broken", encoding="utf-8")
        s, problem = Settings.load(path)
        self.assertFalse(s.subtle)
        self.assertIn("mistake", problem)

    def test_single_instance_and_stop_request(self):
        a, b = SingleInstance(self.dir), SingleInstance(self.dir)
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())
        self.assertTrue(b.is_running())
        b.request_stop()
        self.assertTrue(a.stop_requested())
        a.release()
        self.assertFalse(b.is_running())
        self.assertFalse(a.stop_requested())

    def test_userlog_once_and_plain_lines(self):
        log = UserLog(self.dir / "x.log")
        with mock.patch.object(sys, "stdout", None):   # windowed builds have no console
            log.once("Waiting for Death Stranding to start")
            log.once("Waiting for Death Stranding to start")
            log.info("Stopped service")
        log.close()
        lines = (self.dir / "x.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1].endswith("  Stopped service"))

    def test_status_messages_stay_plain(self):
        from odradek_sync.app.main import StatusMessages
        log = UserLog(self.dir / "s.log")
        msgs = StatusMessages(log)
        for s in (Attach.NO_PROCESS, Attach.NO_PROCESS, Attach.ATTACHED, "reloading", Attach.ATTACHED, "closed",
                  Attach.NO_PROCESS):
            msgs(s)
        log.close()
        text = [l.split("  ", 1)[1] for l in (self.dir / "s.log").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(text, ["Waiting for Death Stranding to start", "Connected to Death Stranding",
                                "Death Stranding closed", "Waiting for Death Stranding to start"])

    @unittest.skipIf(sys.platform == "win32", "XDG files are Linux-only")
    def test_linux_autostart_files(self):
        from odradek_sync.app import autostart
        env = {"XDG_CONFIG_HOME": str(self.dir / "cfg"), "XDG_DATA_HOME": str(self.dir / "data"), "APPIMAGE": "/opt/Odradek Sync.AppImage"}
        with mock.patch.dict(os.environ, env):
            autostart.enable()
            entry = (self.dir / "cfg/autostart/odradek-sync.desktop").read_text(encoding="utf-8")
            self.assertIn("Exec='/opt/Odradek Sync.AppImage'", entry)
            self.assertIn("--stop", (self.dir / "data/applications/odradek-sync-stop.desktop").read_text(encoding="utf-8"))
            self.assertTrue(autostart.is_enabled())
            autostart.disable()
            self.assertFalse(autostart.is_enabled())
            autostart.remove_all()
            self.assertFalse((self.dir / "data/applications/odradek-sync.desktop").exists())


class FakeRepo:
    """Scripted DeviceRepository: list_devices raises or returns what the test says."""

    from odradek_sync.lighting.openrgb_repository import OpenRGBRepository
    HELP = OpenRGBRepository.HELP

    def __init__(self, script):
        self.script, self.resets = list(script), 0

    def list_devices(self):
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        if isinstance(step, Exception):
            raise step
        return step

    def open(self, selector=None):
        from odradek_sync.lighting.console_repository import NullDevice
        return NullDevice(self.list_devices()[0])

    def reset(self):
        self.resets += 1


class ResilientKeyboardTest(unittest.TestCase):
    def test_plain_messages_for_missing_openrgb_then_keyboard(self):
        from odradek_sync.app.keyboard import ResilientKeyboard
        from odradek_sync.config import ConfigLoader
        from odradek_sync.lighting import BackendMissingError, NoDeviceError
        from odradek_sync.lighting.compositor import EffectMap
        from odradek_sync.lighting.console_repository import ConsoleRepository
        from odradek_sync.lighting.device import DeviceInfo, LedInfo

        keys = ["Escape", "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "Q", "W", "E", "Space"]
        no_matrix = DeviceInfo("0", "Mystery KB", "keyboard", tuple(LedInfo(i, k) for i, k in enumerate(keys)))
        with tempfile.TemporaryDirectory() as d:
            log = UserLog(Path(d) / "k.log")
            em = EffectMap.from_dict(ConfigLoader([]).load("effects", "default"))
            repo = FakeRepo([BackendMissingError("x"), BackendMissingError("x"), NoDeviceError("x"), [no_matrix]])
            kb = ResilientKeyboard(log, em, [], repo=repo)
            for t in (0, 1, 40, 80, 120):          # retries are time-based
                kb.update(float(t), {"no_game": True}, None)
            log.close()
            text = [l.split("  ", 1)[1] for l in (Path(d) / "k.log").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(text[0].startswith("OpenRGB is not installed"))
        self.assertTrue(text[1].startswith("No RGB keyboard found"))
        self.assertEqual(text[2], "Keyboard detected: Mystery KB")
        self.assertTrue(text[3].startswith("Using fallback layout for this keyboard: estimated"))
        self.assertEqual(len(text), 4)


if __name__ == "__main__":
    unittest.main()
