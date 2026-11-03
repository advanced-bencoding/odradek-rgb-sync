import dataclasses
import tempfile
import unittest
from pathlib import Path

from fakes import HEAP, MODULE_BASE, PROFILE, FakeMemory, VTABLE_RVA

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


class MultiBuildTest(unittest.TestCase):
    """One profile for several builds that differ only in the vtable (standard edition vs Director's Cut)."""
    OTHER_BUILD_RVA = 0x38703C0
    PROFILE = dataclasses.replace(PROFILE, layout=dataclasses.replace(
        PROFILE.layout, vtable_rvas=(VTABLE_RVA, OTHER_BUILD_RVA)))

    def world(self):
        m = FakeMemory()
        m.add_object("ds/animations/game/odra/odra/an_odra_arm_search", 2, 1, self.OTHER_BUILD_RVA)
        m.add_object("ds/animations/game/odra/odra/an_odra_main_sleep_lp", 4, 2, self.OTHER_BUILD_RVA)
        # in this build the first build's vtable address is unrelated data: a hit on it has no animation name
        m.write(HEAP + 3 * 0xA0, (MODULE_BASE + VTABLE_RVA).to_bytes(8, "little"))
        return m

    def test_finds_the_running_builds_objects_and_keeps_its_vtable(self):
        m = self.world()
        cat = AnimationCatalog(m, self.PROFILE)
        objs = cat.scan()
        self.assertEqual(sorted(o.name for o in objs), ["odra_arm_search", "odra_main_sleep_lp"])
        self.assertEqual(cat.rva, self.OTHER_BUILD_RVA)
        self.assertEqual(list(cat.vtables().values()), [self.OTHER_BUILD_RVA])
        self.assertEqual(len(cat.scan()), 2)
        self.assertTrue(cat.still_valid(objs))

    def test_objects_from_the_cache_validate_against_every_build(self):
        m = self.world()
        objs = AnimationCatalog(m, self.PROFILE).scan()
        fresh = AnimationCatalog(m, self.PROFILE)      # a restarted tool: build not known yet
        self.assertTrue(fresh.still_valid(objs))
        self.assertEqual(fresh.rva, self.OTHER_BUILD_RVA)   # ...until the cached objects are checked
        for o in objs:
            m.write(o.address, b"\0" * 8)
        self.assertFalse(fresh.still_valid(objs))


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

    def test_a_closed_game_still_in_the_process_list_is_not_attached_again(self):
        from odradek_sync.game import Attach, GameSession
        from odradek_sync.game import session as session_mod
        from odradek_sync.platform import ProcessInfo

        m, listed = world(), [True]

        class Plat:
            def find_process(self, exes):
                return ProcessInfo(m.pid, "Game.exe") if listed[0] else None

            def open_process(self, pid):
                return m

        with tempfile.TemporaryDirectory() as d:
            s = GameSession(Plat(), PROFILE, {"odra_arm_search"}, Path(d))
            self.assertEqual(s.try_attach(), Attach.ATTACHED)
            m.alive = False                              # quit: gone, but still listed and readable for a moment
            s._checked -= session_mod.REVALIDATE_EVERY + 1
            self.assertIsNone(s.read())
            m.alive = True                               # a fresh handle can still look alive while it winds down
            self.assertEqual(s.try_attach(), Attach.NO_PROCESS)
            listed[0] = False
            self.assertEqual(s.try_attach(), Attach.NO_PROCESS)
            listed[0], m.pid = True, 5150                # the game started again: a new process
            self.assertEqual(s.try_attach(), Attach.ATTACHED)

    def test_paused_reads_the_builds_pause_indicator(self):
        import struct

        from odradek_sync.config import PauseIndicator
        from odradek_sync.game import Attach, GameSession
        from odradek_sync.platform import ProcessInfo

        m = world()
        speed, flag = MODULE_BASE + 0x44E2424, MODULE_BASE + 0x6CE0869
        m.mem[speed] = bytearray(struct.pack("<f", 1.0))
        m.mem[flag] = bytearray(1)

        class Plat:
            def find_process(self, exes):
                return ProcessInfo(m.pid, "Game.exe")

            def open_process(self, pid):
                return m

        with tempfile.TemporaryDirectory() as d:
            for pause, detects in (({VTABLE_RVA: PauseIndicator(0x44E2424, "speed")}, True),
                                   ({0x123: PauseIndicator(0x44E2424, "speed")}, False)):
                s = GameSession(Plat(), dataclasses.replace(PROFILE, pause=pause), {"odra_arm_search"}, Path(d))
                self.assertEqual(s.try_attach(), Attach.ATTACHED)
                self.assertFalse(s.paused)
                m.write(speed, struct.pack("<f", 0.0))       # pause menu, or the window in the background
                self.assertEqual(s.paused, detects)          # another build's address is never used
                m.write(speed, struct.pack("<f", 1.0))
                self.assertFalse(s.paused)                   # resumed (focus back): playing again
                s.detach()
            # the Director's Cut: a byte, nonzero while paused
            s = GameSession(Plat(), dataclasses.replace(PROFILE, pause={VTABLE_RVA: PauseIndicator(0x6CE0869, "flag")}),
                            {"odra_arm_search"}, Path(d))
            self.assertEqual(s.try_attach(), Attach.ATTACHED)
            self.assertFalse(s.paused)
            m.write(flag, b"\x01")
            self.assertTrue(s.paused)
            m.write(flag, b"\x00")
            self.assertFalse(s.paused)


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
