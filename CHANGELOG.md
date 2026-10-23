# Changelog

All notable changes to odradek-sync. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org) as described in [RELEASING.md](RELEASING.md).

Write entries for players first: what changed for them, in plain words. Mention config format
changes and anything users must do under **Changed** with a ⚠️.

## [Unreleased]

### Added
- ASUS ROG Flow Z13 (2025) support through [z13ctl](https://github.com/dahui/z13ctl), picked
  automatically on a Z13. The keyboard shows each Odradek state with its own built-in effects
  (one colour across the board), and goes back to your own z13ctl lighting when the game isn't
  running. Not tested on a real Z13 yet.
- `--lighting auto` (the new default) picks z13 on a Z13 and OpenRGB everywhere else.
- Tray menu entries to choose the lighting software (OpenRGB, or z13ctl on a Z13). Software that
  isn't installed, or finds no hardware, is greyed out with the reason. Switching is live; if the
  new choice fails, Odradek Sync goes back to the previous one. The choice is saved as `lighting`
  in the settings file.

## [0.1.0] - 2026-10-17

First release. Linux is tested; Windows is built but untested, so this is published as a pre-release.

### Added
- Mirrors the Odradek on an RGB keyboard through OpenRGB by reading Death Stranding Director's Cut's
  animation states from memory (read-only): folded, unfolding, terrain scan, blue (slow, fast and
  rapid pulsing), orange, autotoxemia, and BB's mood on the top row.
- Player app for Linux (AppImage) and Windows (installer). It runs in the background, starts at
  login, logs in plain words, and has a small settings file.
- Tray icon showing whether the game and keyboard are connected (full colour when both are),
  with a menu to switch subtle mode on and off live, toggle start-at-login, open the log or
  settings, and quit.
- Accessibility mode (`subtle`): no strobes or flicker, capped brightness, smooth fades.
- Automatic layouts for keyboards without explicit support: exact when OpenRGB reports a key
  matrix, otherwise estimated (60%, 65%, 75%, tenkeyless or full-size) from key names or LED count.
- Developer tools: `odradek-sync run`, `effects demo`, `signals`, `devices`, and `recon` (list,
  watch with markers, capture/compare, discover) for mapping new animations and game builds.
- Data-driven configuration: game profiles, signal maps, effect maps and device regions in TOML,
  each with a format version.
