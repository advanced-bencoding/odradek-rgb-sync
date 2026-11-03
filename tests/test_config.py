"""The shipped configs must load and agree with each other."""
import unittest

from odradek_sync.config import ConfigError, ConfigLoader, GameProfile
from odradek_sync.lighting.compositor import Compositor, EffectMap
from odradek_sync.lighting.console_repository import ConsoleRepository
from odradek_sync.lighting.geometry import LayoutFactory
from odradek_sync.signals import SignalMap, SignalPipeline


class ShippedConfigTest(unittest.TestCase):
    def setUp(self):
        self.loader = ConfigLoader([])

    def test_every_game_has_a_signal_map(self):
        for g in self.loader.names("games"):
            profile = self.loader.game(g)
            SignalMap.from_dict(self.loader.load("signals", profile.id))

    def test_effect_maps_only_use_known_signals_and_regions(self):
        smap = SignalMap.from_dict(self.loader.load("signals", "death_stranding_dc"))
        known = SignalPipeline(smap).signal_names
        geometry = LayoutFactory().build(ConsoleRepository().info, self.loader.devices())
        for name in self.loader.names("effects"):
            em = EffectMap.from_dict(self.loader.load("effects", name))
            self.assertEqual(em.referenced_signals() - known, set(), name)
            Compositor(em, geometry)
            for demo in em.demos:
                used = set(demo.get("signals", {})) | {b["signal"] for b in demo.get("blink", [])}
                self.assertEqual(used - known, set(), demo["label"])

    def test_aula_f75_is_handed_back_in_off_mode(self):
        from odradek_sync.lighting import device_config
        self.assertEqual(device_config("AULA F75", self.loader.devices())["openrgb"]["release_mode"], "Off")
        self.assertEqual(device_config("Some Other Keyboard", self.loader.devices()), {})

    def test_death_stranding_covers_standard_edition_and_directors_cut(self):
        rvas = self.loader.game("death_stranding_dc").layout.vtable_rvas
        self.assertIn(0x3C12968, rvas)   # Director's Cut
        self.assertIn(0x38703C0, rvas)   # standard edition 1.0.8


class GameProfileTest(unittest.TestCase):
    def profile(self, vtable_rva):
        return GameProfile.from_dict({
            "game": {"id": "g", "name": "G", "executables": ["G.exe"]},
            "animation_objects": {"vtable_rva": vtable_rva, "state_offset": 0x18, "name_offset": 0x28,
                                  "name_filter": "/odra/"}})

    def test_pause_per_build(self):
        from odradek_sync.config import PauseIndicator
        d = {"game": {"id": "g", "name": "G", "executables": ["G.exe"]},
             "animation_objects": {"vtable_rva": [0x10, 0x20], "state_offset": 0x18, "name_offset": 0x28,
                                   "name_filter": "/odra/"},
             "pause": [{"build": 0x10, "rva": 0x500}, {"build": 0x20, "rva": 0x600, "kind": "flag"}]}
        p = GameProfile.from_dict(d)
        self.assertEqual(p.pause, {0x10: PauseIndicator(0x500, "speed"), 0x20: PauseIndicator(0x600, "flag")})
        self.assertEqual(self.profile(0x10).pause, {})
        d["pause"][1]["kind"] = "u32"
        with self.assertRaises(ConfigError):
            GameProfile.from_dict(d)
        shipped = ConfigLoader([]).game("death_stranding_dc").pause
        self.assertEqual(shipped[0x38703C0].kind, "speed")       # standard edition 1.0.8
        self.assertEqual(shipped[0x3C12968].kind, "flag")        # Director's Cut

    def test_pause_indicator_reads(self):
        import struct
        from odradek_sync.config import PauseIndicator
        speed, flag = PauseIndicator(0, "speed"), PauseIndicator(0, "flag")
        self.assertTrue(speed.paused(struct.pack("<f", 0.0)))
        self.assertFalse(speed.paused(struct.pack("<f", 1.0)))
        self.assertTrue(flag.paused(b"\x01"))
        self.assertFalse(flag.paused(b"\x00"))
        self.assertFalse(flag.paused(None))                      # unreadable: carry on as if playing
        self.assertFalse(speed.paused(b"\x00"))                  # short read

    def test_vtable_rva_is_one_build_or_a_list_of_builds(self):
        self.assertEqual(self.profile(0x10).layout.vtable_rvas, (0x10,))
        self.assertEqual(self.profile([0x10, 0x20]).layout.vtable_rvas, (0x10, 0x20))
        for bad in ([], ["0x10"]):
            with self.assertRaises(ConfigError):
                self.profile(bad)


if __name__ == "__main__":
    unittest.main()
