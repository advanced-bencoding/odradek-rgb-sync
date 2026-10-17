import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

CHANGELOG = """# Changelog

## [Unreleased]

### Fixed
- Something players will notice.

## [0.1.0] - 2026-10-17

### Added
- First release.
"""


class ReleaseScriptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.py, self.cl = d / "pyproject.toml", d / "CHANGELOG.md"
        self.py.write_text('[project]\nname = "x"\nversion = "0.1.0"\n', encoding="utf-8")
        self.cl.write_text(CHANGELOG, encoding="utf-8")
        self.patch = mock.patch.multiple(release, PYPROJECT=self.py, CHANGELOG=self.cl)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_python_spelling_of_prereleases(self):
        self.assertEqual(release.to_python("v0.2.0-beta.1"), "0.2.0b1")
        self.assertEqual(release.to_python("1.0.0-rc.2"), "1.0.0rc2")
        with self.assertRaises(SystemExit):
            release.parse("1.0")

    def test_prepare_release_moves_unreleased_notes(self):
        with mock.patch("builtins.print"):
            release.cmd_prepare("0.1.1")
        self.assertIn('version = "0.1.1"', self.py.read_text(encoding="utf-8"))
        self.assertIn("Something players will notice", release.section("0.1.1"))
        self.assertEqual(release.section("Unreleased"), "")
        with mock.patch("builtins.print"):
            release.cmd_check("v0.1.1")

    def test_prepare_prerelease_only_bumps_version(self):
        with mock.patch("builtins.print"):
            release.cmd_prepare("0.2.0-beta.1")
        self.assertIn('version = "0.2.0b1"', self.py.read_text(encoding="utf-8"))
        self.assertIsNone(release.section("0.2.0"))
        with mock.patch("builtins.print"):
            release.cmd_check("v0.2.0-beta.1")

    def test_check_catches_mismatch_and_missing_notes(self):
        with self.assertRaises(SystemExit):
            release.cmd_check("v0.3.0")

    def test_shipped_changelog_matches_shipped_version(self):
        self.patch.stop()
        try:
            v = release.project_version()
            if "+" not in v and not any(c.isalpha() for c in v):
                self.assertTrue(release.section(v), f"CHANGELOG.md needs a [{v}] section")
        finally:
            self.patch.start()


class ConfigFormatTest(unittest.TestCase):
    def test_format_rules(self):
        from odradek_sync.config import ConfigError, check_format
        check_format("effects", {}, "x")                 # missing = 1
        check_format("effects", {"format": 1}, "x")
        with self.assertRaises(ConfigError) as e:
            check_format("effects", {"format": 2}, "mine.toml")
        self.assertIn("Update odradek-sync", str(e.exception))
        with self.assertRaises(ConfigError):
            check_format("effects", {"format": "1"}, "x")

    def test_every_shipped_config_declares_its_format(self):
        import tomllib
        from odradek_sync.config import FORMATS, PACKAGE_CONFIG
        for f in PACKAGE_CONFIG.glob("*/*.toml"):
            self.assertEqual(tomllib.loads(f.read_text(encoding="utf-8")).get("format"), FORMATS[f.parent.name], f.name)


if __name__ == "__main__":
    unittest.main()
