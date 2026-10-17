# Versioning and releases

How odradek-sync numbers its versions, keeps a changelog, versions its config files, and ships
releases. `scripts/release.py` and CI enforce most of this.

## Version numbers

[Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`, git tags `vMAJOR.MINOR.PATCH`.

**We're in 0.x.** That means "useful but still changing". Stay in 0.x until:
- the Windows build has been tested on real Windows, and
- the config formats feel settled.

`1.0.0` is the first stability promise.

| Bump | Rule | Examples |
| --- | --- | --- |
| **PATCH** | Fixes. Nobody has to change anything. | a crash fix, a wrong animation name, an effect that looks off, clearer log wording |
| **MINOR** | New capability. While in 0.x, also anything breaking (flagged ⚠️ in the changelog). | a newly mapped Odradek state, a new effect, keyboard fallback improvements, a new setting, support for a new game build |
| **MAJOR** (from 1.0) | Users must act. | a setting renamed or removed, a config format bump, a CLI command changed or removed |

**When unsure,** ask: "does someone who upgrades have to do anything?"
- No → PATCH (fix) or MINOR (feature).
- Yes → MAJOR. While in 0.x, MINOR with a ⚠️.

**Pre-releases** are for testers. GitHub marks them as pre-releases automatically:
- `vX.Y.Z-beta.N`: feature-complete enough to try. Expect rough edges.
- `vX.Y.Z-rc.N`: we think it's done. If nobody finds problems, the same commit becomes `vX.Y.Z`.
- `-alpha.N` exists too, for very early builds.

**Two spellings, one version.** Tags and the changelog use SemVer (`v0.2.0-beta.1`).
`pyproject.toml` must use Python's spelling (`0.2.0b1`). `scripts/release.py` converts between
them, so you only type the SemVer form.

**There's one place to set the version: `pyproject.toml`.** The code reads it from package
metadata (`odradek_sync.__version__`), and the PyInstaller build copies that metadata into the
app. After changing it locally, run `pip install -e .` so `--version` shows the new number.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

- **Every user-visible change adds a line under `## [Unreleased]`** in the same pull request.
  This covers new mapped states, effects, settings, fixes and log wording. Internal refactors
  and test-only changes don't need one.
- **Group entries** under `### Added`, `### Changed`, `### Deprecated`, `### Removed`, `### Fixed`,
  `### Security`.
- **Write for players first.** "Orange now shows while BTs follow your footprints", not "added
  `odra_main_cross_warrning_sign_lp` to signals.orange". Technical detail can follow in the
  same line if contributors need it.
- **Anything users must act on** goes under `### Changed` and starts with ⚠️, saying what to do:
  "⚠️ `settings.toml`: `quiet` is now called `subtle`; rename it or delete the file".
- **Releases:** `scripts/release.py prepare X.Y.Z` turns `[Unreleased]` into `## [X.Y.Z] - <date>`.
  That section becomes the GitHub release notes. Pre-releases use the current `[Unreleased]`
  notes and don't create a section.

## Config format versions

Every TOML in `config/` (and every user copy of one) starts with `format = N`. A missing key
means 1. The current numbers are in `odradek_sync/config.py` (`FORMATS`).

- **Adding optional keys, or new signals, effects, layers and devices,** doesn't change the format.
- **Bump a kind's format** only when an existing file of that kind would be misread or rejected:
  a key renamed or removed, a meaning changed, a structure changed. Do it like this:
  1. Increase `FORMATS[kind]` and update every shipped file of that kind.
  2. Add a ⚠️ changelog entry explaining how to update a custom file.
  3. Make it a MAJOR release (MINOR with ⚠️ while in 0.x).
- **Files with a different format number are rejected** with a message that says what to do:
  "update odradek-sync", or "update or delete your custom file".
- **Game builds aren't config formats.** Supporting a new game patch or store version means a
  new or updated file in `config/games/` (record it in `verified_builds`) and a MINOR release.
  Name the build in the release notes.

## Making a release

Prerequisites: everything you want is merged into `main`, tests pass, and `[Unreleased]` has notes.

```bash
python scripts/release.py prepare 0.2.0      # bumps pyproject.toml, dates the changelog section
git diff                                     # check both files
git commit -am "Release 0.2.0" && git push
git tag v0.2.0 && git push origin v0.2.0     # this starts the build
```

The tag triggers `.github/workflows/release.yml`:

1. **Release check:** the tag must match `pyproject.toml`, and a final release needs its
   changelog section. A mismatch fails the run before anything is built.
2. **Tests,** then the **Linux AppImage** (Ubuntu 22.04, for an older glibc) and the **Windows
   installer** are built in parallel.
3. **A draft release** is created with both files attached, the changelog section as its notes,
   and the pre-release flag set for `-alpha/-beta/-rc` tags.

Then by hand, on GitHub → Releases:

4. **Smoke-test the downloads.**
   - Linux: run the AppImage and check its log.
   - Windows: install on a real PC, start it, check the log, uninstall.
   - Until Windows is verified, tick **"Set as a pre-release"** even for `vX.Y.Z` tags.
5. **Publish** the draft.

**Pre-release:** the same steps with `prepare 0.2.0-beta.1` and tag `v0.2.0-beta.1`.

**Builds without releasing:** Actions → "Build player apps" → **Run workflow**. Both apps appear
as artifacts on that run; no tag and no release.

### When a release build fails

Fix it on `main`, then point the tag at the fixed commit. Only do this while the release is
still a draft:

```bash
git tag -d v0.2.0 && git push --delete origin v0.2.0
git tag v0.2.0 && git push origin v0.2.0
```

Delete the old draft release on GitHub. **Never move a tag that has been published.** If a
published release is broken, release the next PATCH version.

## Checklist

- [ ] `[Unreleased]` describes every user-visible change, with ⚠️ for anything users must do
- [ ] tests pass (`python -m unittest discover -s tests`)
- [ ] the right bump (PATCH / MINOR / MAJOR) per the table above
- [ ] `python scripts/release.py prepare X.Y.Z`, commit, push, tag, push the tag
- [ ] CI green; draft release has the AppImage and the setup.exe
- [ ] downloads smoke-tested (Windows on a real PC)
- [ ] published (as pre-release while Windows is unverified)
