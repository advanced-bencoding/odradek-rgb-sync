"""The shipped configs must load and agree with each other."""
import unittest

from odradek_sync.config import ConfigLoader
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


if __name__ == "__main__":
    unittest.main()
