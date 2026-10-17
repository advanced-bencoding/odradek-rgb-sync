import tempfile
import unittest
from pathlib import Path

from fakes import PROFILE, FakeMemory, VTABLE_RVA

from odradek_sync.game import AnimationCatalog, CatalogCache, StateReader


def world():
    m = FakeMemory()
    m.add_object("ds/animations/game/odra/odra/an_odra_arm_search", 2, 1)
    m.add_object("ds/animations/game/odra/odra/an_odra_main_warrning_sign_lp", 3, 2)
    m.add_object("ds/animations/game/sam/sampho/an_sam_walk", 3, 3)      # filtered out by name
    m.add_object("ds/animations/game/odra/odra/an_odra_main_sleep_lp", 4, 200)  # far away: second read group
    return m


class CatalogTest(unittest.TestCase):
    def test_scan_finds_objects_by_vtable_and_filters_names(self):
        m = world()
        objs = AnimationCatalog(m, PROFILE).scan()
        self.assertEqual(sorted(o.name for o in objs),
                         ["odra_arm_search", "odra_main_sleep_lp", "odra_main_warrning_sign_lp"])

    def test_reader_groups_and_reads_states(self):
        m = world()
        objs = AnimationCatalog(m, PROFILE).scan()
        r = StateReader(m, PROFILE, objs)
        self.assertEqual(len(r.groups), 2)
        self.assertEqual(r.read(), {"odra_arm_search": 2, "odra_main_warrning_sign_lp": 3, "odra_main_sleep_lp": 4})
        m.set_state("ds/animations/game/odra/odra/an_odra_arm_search", 3)
        self.assertEqual(r.read()["odra_arm_search"], 3)

    def test_still_valid_detects_moved_objects(self):
        m = world()
        cat = AnimationCatalog(m, PROFILE)
        objs = cat.scan()
        self.assertTrue(cat.still_valid(objs))
        for o in objs:
            m.write(o.address, b"\0" * 8)
        self.assertFalse(cat.still_valid(objs))

    def test_cache_round_trip_is_keyed_by_pid(self):
        m = world()
        objs = AnimationCatalog(m, PROFILE).scan()
        with tempfile.TemporaryDirectory() as d:
            c = CatalogCache(Path(d) / "c.json")
            c.save(1, "test", "/odra/", objs)
            self.assertEqual(c.load(1, "test", "/odra/"), objs)
            self.assertIsNone(c.load(2, "test", "/odra/"))


class SessionTest(unittest.TestCase):
    def test_game_exiting_mid_read_detaches_instead_of_crashing(self):
        from odradek_sync.game import Attach, GameSession
        from odradek_sync.game import session as session_mod

        m = world()

        class Plat:
            def find_process(self, exes):
                from odradek_sync.platform import ProcessInfo
                return ProcessInfo(m.pid, "Game.exe") if m.alive else None

            def open_process(self, pid):
                return m

        with tempfile.TemporaryDirectory() as d:
            s = GameSession(Plat(), PROFILE, {"odra_arm_search"}, Path(d))
            self.assertEqual(s.try_attach(), Attach.ATTACHED)
            self.assertIsNotNone(s.read())
            m.module_range = lambda name: None          # exe unmapped, process still alive
            s._checked -= session_mod.REVALIDATE_EVERY + 1
            self.assertIsNone(s.read())                  # no exception
            self.assertEqual(s.try_attach(), Attach.NOT_LOADED)
            m.alive = False
            self.assertEqual(s.try_attach(), Attach.NO_PROCESS)


class DiscoverTest(unittest.TestCase):
    def test_discovers_outer_object_layout(self):
        try:
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("numpy not installed")
        from odradek_sync.recon import discover_layout
        m = world()
        best = discover_layout(m, "Game.exe", b"ds/animations/")[0]
        self.assertEqual((best.vtable_rva, best.name_offset), (VTABLE_RVA, 0x28))
        self.assertEqual(best.state_offsets[0][0], 0x18)


if __name__ == "__main__":
    unittest.main()
