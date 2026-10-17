#!/usr/bin/env python3
"""Release helper. Keeps pyproject.toml, CHANGELOG.md and git tags consistent (see RELEASING.md).

    python scripts/release.py prepare 0.2.0          # bump version, move [Unreleased] to [0.2.0] - today
    python scripts/release.py prepare 0.2.0-beta.1   # pre-release: bump version only
    python scripts/release.py check v0.2.0           # CI: tag matches pyproject + changelog has the section
    python scripts/release.py notes v0.2.0           # print the changelog section (release notes)

Tags and the changelog use SemVer spelling (v0.2.0-beta.1); pyproject.toml uses Python's
(0.2.0b1). This script converts between them, so you only ever type the SemVer form.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
CHANGELOG = ROOT / "CHANGELOG.md"
SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?$")
PEP440_PRE = {"alpha": "a", "beta": "b", "rc": "rc"}


def parse(v: str) -> re.Match:
    m = SEMVER.match(v)
    if not m:
        sys.exit(f"'{v}' isn't a release version: use X.Y.Z or X.Y.Z-alpha.N / -beta.N / -rc.N")
    return m


def to_python(v: str) -> str:
    m = parse(v)
    base = ".".join(m.group(1, 2, 3))
    return base + (f"{PEP440_PRE[m.group(4)]}{m.group(5)}" if m.group(4) else "")


def plain(v: str) -> str:
    return v.removeprefix("v")


def is_prerelease(v: str) -> bool:
    return parse(v).group(4) is not None


def project_version() -> str:
    m = re.search(r'(?m)^version = "([^"]+)"', PYPROJECT.read_text(encoding="utf-8"))
    if not m:
        sys.exit("no version in pyproject.toml")
    return m.group(1)


def section(version: str) -> str | None:
    """Body of '## [version] ...' in the changelog, or None."""
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"(?ms)^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text)
    return m.group(1).strip() if m else None


def cmd_prepare(v: str) -> None:
    v = plain(v)
    parse(v)
    current = project_version()
    if current == to_python(v):
        sys.exit(f"pyproject.toml is already at {current}")
    text = re.sub(r'(?m)^version = "[^"]+"', f'version = "{to_python(v)}"', PYPROJECT.read_text(encoding="utf-8"), count=1)
    PYPROJECT.write_text(text, encoding="utf-8")
    if not is_prerelease(v):
        text = CHANGELOG.read_text(encoding="utf-8")
        unreleased = section("Unreleased")
        if not unreleased:
            sys.exit("CHANGELOG.md has nothing under [Unreleased]; write the release notes first "
                     "(pyproject.toml was updated)")
        today = dt.date.today().isoformat()
        text = text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n## [{v}] - {today}\n", 1)
        CHANGELOG.write_text(re.sub(r"\n{3,}", "\n\n", text), encoding="utf-8")
    print(f"Version {current} -> {to_python(v)}" + ("" if is_prerelease(v) else f"; changelog section [{v}] created"))
    print("Next:\n"
          f"  git commit -am \"Release {v}\" && git push\n"
          f"  git tag v{v} && git push origin v{v}")


def cmd_check(tag: str) -> None:
    v = plain(tag)
    parse(v)
    problems = []
    if project_version() != to_python(v):
        problems.append(f"tag {tag} needs version = \"{to_python(v)}\" in pyproject.toml (it is {project_version()!r})")
    if not is_prerelease(v) and not section(v):
        problems.append(f"CHANGELOG.md has no '## [{v}] - <date>' section with notes")
    if problems:
        sys.exit("Release check failed:\n  " + "\n  ".join(problems))
    print(f"{tag}: OK ({'pre-release' if is_prerelease(v) else 'release'})")


def cmd_notes(tag: str) -> None:
    v = plain(tag)
    body = section("Unreleased") if is_prerelease(v) else section(v)
    if is_prerelease(v):
        body = "Pre-release for testing.\n\n" + (body or "")
    print(body or "")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("prepare", "check", "notes"):
        sys.exit(__doc__)
    {"prepare": cmd_prepare, "check": cmd_check, "notes": cmd_notes}[sys.argv[1]](sys.argv[2])
