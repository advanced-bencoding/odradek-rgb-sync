import json
import socketserver
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from odradek_sync.config import ConfigError, ConfigLoader
from odradek_sync.lighting import BackendMissingError, DeviceError, FirmwareMode, NoDeviceError, detect_backend
from odradek_sync.lighting.compositor import Compositor, EffectMap
from odradek_sync.lighting.geometry import LayoutFactory
from odradek_sync.lighting import z13_repository as z13

KEYBOARD, LIGHTBAR = "HID_ID=0003:00000B05:00001A30", "HID_ID=0003:00000B05:000018C6"
AURA_DESC = bytes([0x06, 0x31, 0xFF, 0x85, 0x5D, 0x09, 0x76])
OTHER_DESC = bytes([0x05, 0x01, 0x85, 0x01, 0x09, 0x06])
SAVED = {"lighting": {"enabled": True, "mode": "breathe", "color": "00FFFF", "color2": "0000FF", "speed": "slow",
                      "brightness": 2}}


class FakeDaemon:
    """z13ctl's socket: records each request and answers like the daemon (get-state returns `state`)."""

    def __init__(self, path: str, state: dict):
        self.requests, self.state = [], state
        daemon = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                req = json.loads(self.rfile.readline())
                daemon.requests.append(req)
                resp = {"ok": True, "state": daemon.state} if req["cmd"] == "get-state" else {"ok": True}
                self.wfile.write((json.dumps(resp) + "\n").encode())

        self.server = socketserver.UnixStreamServer(path, Handler)
        threading.Thread(target=self.server.serve_forever, args=(0.02,), daemon=True).start()

    def lighting(self):
        """The lighting requests, without the get-state reads."""
        return [r for r in self.requests if r["cmd"] != "get-state"]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class Clock:
    def __init__(self):
        self.wall, self.mono = 1000.0, 50.0

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def tick(self, s, slept=0.0):
        self.wall += s + slept
        self.mono += s


@unittest.skipUnless(z13.Z13_PLATFORM, "the Z13 backend is Linux-only (and its fake daemon needs Unix sockets)")
class Z13Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.sysfs = self.dir / "hidraw"
        self.node("hidraw0", KEYBOARD, OTHER_DESC)      # the keyboard's ordinary input interface
        self.node("hidraw1", KEYBOARD, AURA_DESC)
        self.node("hidraw2", LIGHTBAR, AURA_DESC)
        self.node("hidraw3", "HID_ID=0003:0000258A:0000010C", AURA_DESC)
        self.sock = str(self.dir / "z13ctl.sock")
        self.daemon = FakeDaemon(self.sock, SAVED)
        self.clock = Clock()
        patcher = mock.patch.object(z13, "time", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.daemon.stop()
        self.tmp.cleanup()

    def node(self, name, hid_id, desc):
        d = self.sysfs / name / "device"
        d.mkdir(parents=True)
        (d / "uevent").write_text(f"DRIVER=hid-generic\n{hid_id}\nHID_NAME=x\n", encoding="ascii")
        (d / "report_descriptor").write_bytes(desc)

    def repo(self):
        return z13.Z13Repository(self.sock, self.sysfs)

    def compositor(self, device, name="z13"):
        em = EffectMap.from_dict(ConfigLoader([]).load("effects", name))
        return Compositor(em, LayoutFactory().build(device.info))

    def test_finds_each_zones_aura_interface_from_sysfs(self):
        self.assertEqual(z13.find_zones(self.sysfs), {"keyboard": "/dev/hidraw1", "lightbar": "/dev/hidraw2"})
        self.assertTrue(z13.z13_present(self.sysfs))
        self.assertFalse(z13.z13_present(self.dir / "nothing"))
        names = [(d.id, d.kind, d.led_count) for d in self.repo().list_devices()]
        self.assertEqual(names, [("keyboard", "keyboard", 1), ("lightbar", "ledstrip", 1)])

    def test_auto_detection_picks_z13_only_on_a_z13(self):
        with mock.patch.object(z13, "SYSFS", self.sysfs):
            self.assertEqual(detect_backend(), "z13")
        with mock.patch.object(z13, "SYSFS", self.dir / "nothing"):
            self.assertEqual(detect_backend(), "openrgb")

    def test_sends_only_mode_changes_by_raw_path(self):
        kb = self.repo().open()
        self.assertEqual(kb.path, "/dev/hidraw1")
        c = self.compositor(kb)
        for _ in range(3):                              # the same state for a few frames: one request
            kb.render(c, self.clock.time(), {"folded": True})
            self.clock.tick(0.03)
        kb.render(c, self.clock.time(), {"blue": True, "blue_pulse": "rapid"})
        self.assertEqual(self.daemon.lighting(), [
            {"cmd": "apply", "device": "/dev/hidraw1", "mode": "breathe", "color": "1A0F04", "color2": "0A0602",
             "speed": "slow", "brightness": 3},
            {"cmd": "apply", "device": "/dev/hidraw1", "mode": "breathe", "color": "146EFF", "color2": "0A3780",
             "speed": "fast", "brightness": 3},
        ])

    def test_nothing_to_show_hands_back_the_players_lighting(self):
        kb = self.repo().open()
        c = self.compositor(kb)
        kb.render(c, self.clock.time(), {"folded": True})
        kb.render(c, self.clock.time(), {"no_game": True})
        self.assertEqual(self.daemon.lighting()[-1], {"cmd": "apply", "device": "/dev/hidraw1", "mode": "breathe",
                                                      "color": "00FFFF", "color2": "0000FF", "speed": "slow",
                                                      "brightness": 2})
        self.daemon.state = {"lighting": SAVED["lighting"], "devices": {"keyboard": {"enabled": False}}}
        kb.render(c, self.clock.time(), {"folded": True})
        kb.close()
        self.assertEqual(self.daemon.lighting()[-1], {"cmd": "off", "device": "/dev/hidraw1"})

    def test_resends_after_connecting_and_after_sleep(self):
        kb = self.repo().open()
        c = self.compositor(kb)
        kb.render(c, self.clock.time(), {"folded": True})
        for _ in range(int(30 / 0.5)):                  # 30 s in the same state
            self.clock.tick(0.5)
            kb.render(c, self.clock.time(), {"folded": True})
        self.assertEqual(len(self.daemon.lighting()), 1 + len(z13.RESEND_AFTER))
        self.clock.tick(0.03, slept=600)                # the machine slept for ten minutes
        kb.render(c, self.clock.time(), {"folded": True})
        for _ in range(int(30 / 0.5)):
            self.clock.tick(0.5)
            kb.render(c, self.clock.time(), {"folded": True})
        self.assertEqual(len(self.daemon.lighting()), 1 + 2 * len(z13.RESEND_AFTER))

    def test_detached_keyboard_is_a_lost_device(self):
        kb = self.repo().open()
        c = self.compositor(kb)
        kb.render(c, self.clock.time(), {})
        (self.sysfs / "hidraw1" / "device" / "uevent").unlink()
        (self.sysfs / "hidraw1" / "device" / "report_descriptor").unlink()
        (self.sysfs / "hidraw1" / "device").rmdir()
        (self.sysfs / "hidraw1").rmdir()
        with self.assertRaises(NoDeviceError):
            kb.render(c, self.clock.time(), {"folded": True})
        self.assertEqual([d.id for d in self.repo().list_devices()], ["lightbar"])

    def test_only_firmware_effects_run_on_the_z13(self):
        kb = self.repo().open()
        with self.assertRaises(ConfigError):
            kb.render(self.compositor(kb, "default"), self.clock.time(), {})
        with self.assertRaises(DeviceError):
            kb.show([(255, 0, 0)])

    def test_brightness_zero_is_off_not_black(self):
        kb = self.repo().open()
        kb.apply(FirmwareMode("static", (255, 0, 0), brightness=0))
        self.assertEqual(self.daemon.lighting(), [{"cmd": "off", "device": "/dev/hidraw1"}])

    def test_missing_z13ctl_or_its_daemon(self):
        repo = z13.Z13Repository(str(self.dir / "no.sock"), self.sysfs)
        with mock.patch.object(z13.shutil, "which", return_value=None):
            with self.assertRaises(BackendMissingError):
                repo.open()
        with mock.patch.object(z13.shutil, "which", return_value="/usr/bin/z13ctl"):
            with self.assertRaises(DeviceError):
                repo.open()

    def test_player_app_explains_what_a_z13_needs(self):
        from odradek_sync.app.keyboard import ResilientKeyboard
        from odradek_sync.app.userlog import UserLog
        log = UserLog(self.dir / "k.log")
        em = EffectMap.from_dict(ConfigLoader([]).load("effects", "z13"))
        repo = z13.Z13Repository(str(self.dir / "no.sock"), self.sysfs)
        with mock.patch.object(z13.shutil, "which", return_value=None):
            ResilientKeyboard(log, em, [], repo=repo).update(0.0, {"no_game": True}, None)
        kb = ResilientKeyboard(log, em, [], repo=self.repo())
        kb.update(40.0, {"folded": True}, None)
        log.close()
        text = [l.split("  ", 1)[1] for l in (self.dir / "k.log").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(text[0].startswith("This is an ASUS ROG Flow Z13"))
        self.assertEqual(text[1], "Keyboard detected: ASUS ROG Flow Z13 keyboard")
        self.assertEqual(len(text), 2)                  # an exact 1x1 layout: no fallback-layout notice
        self.assertEqual(self.daemon.lighting()[-1]["color"], "1A0F04")



class Z13AnywhereTest(unittest.TestCase):
    """What holds on every system, Windows included."""

    def test_player_lighting_follows_z13ctl_normalisation(self):
        self.assertEqual(z13.player_lighting({}, "keyboard"), z13.Z13CTL_DEFAULT)
        own = {"lighting": SAVED["lighting"], "devices": {"lightbar": {"enabled": True, "mode": "static",
                                                                      "color": "FFFFFF", "brightness": 1}}}
        self.assertEqual(z13.player_lighting(own, "keyboard"), SAVED["lighting"])
        bar = z13.player_lighting(own, "lightbar")
        self.assertEqual((bar["mode"], bar["color"], bar["color2"], bar["speed"], bar["brightness"]),
                         ("static", "FFFFFF", "0000FF", "slow", 1))

    def test_linux_only(self):
        from odradek_sync.lighting import backend_status
        with mock.patch.object(z13, "Z13_PLATFORM", False):
            self.assertEqual(backend_status()["z13"], "Linux only")
            with self.assertRaises(BackendMissingError) as e:
                z13.Z13Repository("unused.sock", "unused").open()
            self.assertIn("Linux only", str(e.exception))


if __name__ == "__main__":
    unittest.main()
