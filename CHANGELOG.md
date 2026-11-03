# Changelog

All notable changes to odradek-sync. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org) as described in [RELEASING.md](RELEASING.md).

Write entries for players first: what changed for them, in plain words. Mention config format
changes and anything users must do under **Changed** with a ⚠️.

## [Unreleased]

## [1.0.0] - 2026-11-03

First full release, no longer a pre-release. Tested on Windows 10 with Death Stranding standard
edition 1.0.8 (the installer, the tray app, start at login, uninstalling) and on Linux with the
Director's Cut under Proton.

### Added
- Support for the standard edition of Death Stranding (version 1.0.8, Epic Games Store) as well as
  the Director's Cut. Odradek Sync works out which one you're running by itself.
- The keyboard shows when a BT detects you (steady orange, as the Odradek freezes and points at it)
  and when you're caught in the tar (an orange wing sweeping over blue, like the Odradek's own),
  until you escape. BB's crying on the top row now lasts through the tar too.
- Pausing the game (the pause menu, or switching to another window) rests the keyboard in its
  no-game look until you resume. Standard edition 1.0.8 only for now; the Director's Cut needs its
  pause address found first.
- Odradek Sync only takes over the keyboard while the game runs. Before and after (and when you quit
  it), the keyboard gets its own lighting back: on the AULA F75 that brings back its styles and the
  knob that switches them, which stop working while OpenRGB has it in Direct mode (OpenRGB does that
  every time it detects the keyboard). Other keyboards get back the mode they were in, or the
  no-game look as before.
- Windows scripts for developers: `scripts\run.cmd` runs the keyboard sync, `scripts\record.cmd`
  records every animation while you play, for mapping new states.
- ASUS ROG Flow Z13 (2025) support on Linux through [z13ctl](https://github.com/dahui/z13ctl),
  picked automatically on a Z13 (not on Windows: z13ctl is Linux-only). The keyboard shows each Odradek state with its own built-in effects
  (one colour across the board), and goes back to your own z13ctl lighting when the game isn't
  running. Not tested on a real Z13 yet.
- `--lighting auto` (the new default) picks z13 on a Z13 and OpenRGB everywhere else.
- Tray menu entries to choose the lighting software (OpenRGB, or z13ctl on a Z13 with Linux). Software that
  isn't installed, or finds no hardware, is greyed out with the reason. Switching is live; if the
  new choice fails, Odradek Sync goes back to the previous one. The choice is saved as `lighting`
  in the settings file.

### Fixed
- Windows: finding the Odradek after the game starts, or after an area loads, took about a minute
  and a half; it now takes about 15 seconds. The developer tools now work on Windows (tested on
  Windows 10).
- The log no longer says "Connected to Death Stranding" for a moment while the game is closing.

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
