import tempfile
import unittest
from pathlib import Path

from odradek_sync.app.settings import Settings
from odradek_sync.app.tray import NullTray, TrayState, menu_items


class TrayModelTest(unittest.TestCase):
    def test_menu_has_status_lines_then_actions(self):
        items = menu_items(TrayState(lines=("Connected to Death Stranding", "Keyboard: AULA F75"), subtle=True))
        self.assertEqual([m.label for m in items[:2]], ["Connected to Death Stranding", "Keyboard: AULA F75"])
        self.assertFalse(items[0].enabled)
        actions = {m.action: m for m in items if m.action}
        self.assertEqual(set(actions), {"toggle_subtle", "toggle_autostart", "open_log", "open_settings", "quit"})
        self.assertTrue(actions["toggle_subtle"].checked)
        self.assertEqual(len({m.id for m in items}), len(items))   # ids are unique

    def test_status_board_drives_lines_and_icon(self):
        from odradek_sync.app.main import StatusBoard
        tray = NullTray(lambda a: None)
        board = StatusBoard(tray)
        board.set_keyboard("Keyboard: AULA F75", True)
        self.assertFalse(tray.state.active)
        board.set_game("Connected to Death Stranding", True)
        self.assertTrue(tray.state.active)
        self.assertEqual(tray.state.lines, ("Connected to Death Stranding", "Keyboard: AULA F75"))

    def test_settings_save_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "settings.toml"
            Settings(subtle=True, autostart=False, keyboard='My "KB"').save(path)
            s, problem = Settings.load(path)
            self.assertEqual((s.subtle, s.autostart, s.keyboard, problem), (True, False, "My KB", None))


class SniEncodingTest(unittest.TestCase):
    def setUp(self):
        try:
            from odradek_sync.app.tray import sni
        except ImportError:
            self.skipTest("jeepney not installed")
        self.sni = sni

    def test_dbusmenu_layout_and_properties(self):
        items = menu_items(TrayState(lines=("Waiting_for",), subtle=False))
        root = self.sni.layout(items)
        self.assertEqual(root[0], 0)
        kids = [c[1] for c in root[2]]
        self.assertTrue(all(sig == "(ia{sv}av)" for sig, _ in root[2]))
        self.assertEqual(kids[0][1]["label"], ("s", "Waiting__for"))      # '_' escaped (mnemonics)
        self.assertEqual(kids[0][1]["enabled"], ("b", False))
        self.assertIn(("type", ("s", "separator")), kids[1][1].items())
        subtle = next(k for k in kids if k[1].get("toggle-type"))
        self.assertEqual(subtle[1]["toggle-state"], ("i", 0))

    def test_icon_pixmaps_have_the_right_size(self):
        from odradek_sync.app.icon import argb32
        self.assertEqual(len(argb32(22)), 22 * 22 * 4)


if __name__ == "__main__":
    unittest.main()
