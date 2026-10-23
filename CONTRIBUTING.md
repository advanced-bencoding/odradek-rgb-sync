# Contributing

Thanks for helping! This file covers the development setup, how the code is laid out, and step-
by-step guides for the common extensions: mapping a new Odradek state, adding an effect,
supporting a new keyboard, a new lighting backend, a new OS, or a new game build.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -e ".[all]"
.venv/bin/python -m unittest discover -s tests      # no game or hardware needed
```

The core package only uses the standard library. Optional dependencies (`openrgb-python`,
`numpy`) are imported lazily, where they're used, so missing extras fail with a clear message
instead of an import error.

## Architecture

```
src/odradek_sync/
  platform/      Platform + ProcessMemory interfaces; linux.py (/proc), windows.py (ReadProcessMemory)
  game/          catalog.py: find animation objects by vtable, read names, StateReader, cache
                 session.py: attach/detach, wait for loads, revalidate when objects move
  signals/       mapping.py: SignalMap (animations -> booleans, from TOML)
                 derivers.py: plug-ins that derive richer signals over time (pulse_rate)
  lighting/      device.py: DeviceRepository / LightingDevice interfaces + registry
                 openrgb_repository.py, z13_repository.py, console_repository.py: backends
                 geometry.py: Geometry, LayoutStrategy (matrix, linear) + LayoutFactory
                 effects/: Effect base, registry/factory, built-in effects
                 compositor.py: EffectMap (TOML) + Compositor (layers, rules, blending)
  outputs.py     Output interface: LightingOutput, StatusPrinter, Recorder (JSONL)
  engine.py      the loop: session -> pipeline -> outputs
  recon/         list, watch (with markers), capture/compare, discover (layout for new builds)
  cli.py         argparse front end
  config/        shipped TOML defaults (games, signals, effects, devices)
```

The layers depend only downward. Effects don't know about the game, and the game layer doesn't
know about lighting. Data such as offsets, animation names, effect choices and key regions lives
in TOML, not in code.

### Extension points

| To add… | Implement | Register with |
| --- | --- | --- |
| an OS / memory backend | `platform.base.Platform` + `ProcessMemory` | `platform.register_platform(prefix, factory)` |
| a game build or game | a TOML in `config/games/` (+ `config/signals/`) | file name = `--game` |
| a derived signal | `signals.derivers.Deriver` | `@register_deriver("kind")`, then `[[derived]] kind = ...` |
| a lighting backend | `lighting.device.DeviceRepository` + `LightingDevice` | `lighting.register_repository(name, factory)` |
| a device shape | `lighting.geometry.LayoutStrategy` | `LayoutFactory().register(strategy)` |
| device-specific regions | a TOML in `config/devices/` | matched by device name |
| an effect | `lighting.effects.Effect` | `@register_effect("name")` |
| an output (MQTT, serial...) | `outputs.Output` | add it in `cli.cmd_run` |

## Mapping a new Odradek state

This is how every mapped signal was found. Example: the unmapped "static orange while BTs follow
you".

1. **Watch while it happens.** Start `odradek-sync recon watch --log follow.jsonl` and play.
   When the state starts, type a note (`static orange now`) and press Enter. The note shows up
   as a `MARK` line in the output and in the log.
2. **Read around the marker.** Animations that start at the marker and stop when the state ends
   are your candidates. Ignore the ones that change all the time.
3. **Confirm with captures.** Take two or three captures while in the state
   (`recon capture follow`), and two or three in a neighbouring state
   (`recon capture orange`, `recon capture blue`). Then run `recon compare`. Animations that are
   steady within each label and differ between labels are listed.
4. **Add it to the signal map** (`config/signals/death_stranding_dc.toml`):
   ```toml
   [signals.bt_following]
   animations = ["odra_main_..."]
   confidence = "weak"          # raise it as evidence accumulates
   description = "Static orange while BTs follow your footprints"
   evidence = "recon watch: on at every 'follow' marker (3/3), off when they lost track"
   ```
5. **Give it an effect** in `config/effects/default.toml`, in the right priority position. Rules
   higher in a layer win. Add a `[[demo]]` scenario so it can be previewed.
6. **Run the tests.** `test_config.py` checks that every signal an effect map uses exists.

**Confidence levels.**
- `confirmed`: verified against independently logged events several times, including at least
  one negative check (it doesn't fire when the event doesn't happen).
- `likely`: matches every observation so far, but with few observations.
- `weak`: a single sighting, or a guess from the animation's name.

Keep `evidence` honest, because the signal map is the project's knowledge base.

**Gotchas we hit:**
- **BB's animations** often move together with the Odradek's, but not always. BB's autotoxemia
  loop once ran alone while the Odradek worked normally. Prefer the Odradek's own animations.
- **Play state 4** means "held" (e.g. `sleep_lp` while folded). Signals can set `state = 4`.
- **Some properties aren't animation states.** Orange spin speed is one: rapid vs slow spinning
  changes no animation. Those need a different technique (see RESEARCH.md, open questions).
- **Pausing** freezes animation states, so recordings show the last state during a pause.

## Adding an effect

```python
from odradek_sync.lighting.effects import Effect, register_effect
from odradek_sync.util import scale

@register_effect("heartbeat")
class Heartbeat(Effect):
    """Double pulse like a heartbeat. params: color, bpm."""

    def setup(self):
        self.c, self.bpm = self.color(), float(self.p("bpm", 70))

    def render(self, t, ctx):
        ph = (t * self.bpm / 60) % 1
        k = max(0.0, 1 - abs(ph - 0.1) * 12) + max(0.0, 1 - abs(ph - 0.3) * 12)
        return self.each(ctx, lambda i, pos: scale(self.c, min(1.0, k)))
```

If your effect flashes or moves fast, check how it looks with `--subtle` too. The subtle map
should only use effects that stay calm: steady, breathing or slow motion. The `[accessibility]`
filter (`Softener` in `compositor.py`) caps brightness and smooths whatever you render.

Effects receive a `FrameContext` with the `geometry` (LED positions in key units plus named
regions), the current `signals`, and `rises` (when each signal last turned on, used by
`flash_mirror`). Keep effects device-independent: use positions, `geometry.point("center")` and
regions, never LED indices. Built-in effects live in `lighting/effects/builtin.py`, and a test
checks that every registered effect renders.

## Supporting a new keyboard

Most keyboards need nothing. `LayoutFactory` tries these strategies in order
(`lighting/geometry.py`):

1. **`MatrixLayout`:** OpenRGB reports a key matrix. Exact.
2. **`NamedKeyLayout`:** no matrix, but at least 60% of the LED names are keys ("Key: Escape",
   "Esc", "LCtrl", "Numpad 7"...; see `keyboard_layouts.canonical`). The size is worked out from
   which keys exist:
   - number pad → **full**
   - F-row + Insert/Home/PgUp + Scroll Lock/Pause → **TKL**
   - F-row → **75%**
   - arrows → **65%**
   - otherwise **60%**

   Keys are then placed on that size's reference layout. LEDs that aren't keys (logo, light bar)
   are left unplaced.
3. **`EstimatedKeyboardLayout`:** names unusable ("LED 12"). The size comes from the LED count,
   and LEDs are laid out in reading order. Approximate: effects cover the right area, but
   individual keys may be off, because backends list LEDs in different orders.
4. **`LinearLayout`:** not a keyboard (strips, mice). One row.

`odradek-sync devices` shows which strategy was used and the regions it produced. Regions come
from positions and key names, for every keyboard:
- `top_row` / `bottom_row`: the highest / lowest row with keys. On a 60% board that's the number
  row and Esc.
- `left_half`, `right_half`
- when present: `frow`, `number_row`, `arrows`, `wasd`, `numpad`

Add `config/devices/<name>.toml` only to fix or extend the result, for example a top row that
isn't the highest row, or custom key groups. Keys match OpenRGB names or the same variants:

```toml
[device]
match = "BrandName Model"           # substring of the device name
[regions]
top_row = { rows = [0] }
macro_keys = { keys = ["G1", "G2", "G3"] }
```

To improve the fallback itself, add aliases to `keyboard_layouts._ALIASES`, a size class to
`keyboard_layouts`, or a new `LayoutStrategy` (e.g. for ISO or split boards). Then register it
with `LayoutFactory().register(...)`. `tests/test_layouts.py` round-trips every size class.

## A new lighting backend

Implement `DeviceRepository.list_devices()` / `open()` and a `LightingDevice.show(colors)`, then
register it. Give the repository a `HELP` table so the player app can explain problems in its
words. Candidates: Razer Chroma / Logitech LIGHTSYNC SDKs on Windows, Windows Dynamic Lighting,
Home Assistant, WLED. Look at `console_repository.py` for the smallest example.

Hardware that can't take frames, only switch between effects its firmware runs (the ROG Flow Z13),
is a `FirmwareModeDevice`: it implements `apply(FirmwareMode | None)` instead of `show()`. It shows
the top layer's effect, which must carry a `firmware_mode` (the `aura` effect does), so it needs
an effect map of its own (`config/effects/z13.toml`), and `lighting.default_effects` picks it.
`apply(None)` means nothing is showing: hand the device back to its owner's lighting.
`z13_repository.py` is the example; `lighting.detect_backend()` decides which backend `auto` uses.

## Windows: help verify

The Windows backend (`platform/windows.py`) uses `ReadProcessMemory`, `VirtualQueryEx` and
Toolhelp snapshots, but nobody has run it on Windows yet. To verify:

1. `odradek-sync recon list --active` while the game runs. Do Odradek animations appear?
2. `odradek-sync run --lighting none`, then fold and unfold the Odradek with a scan. Do the
   status lines follow?
3. Report results, including the game store (Steam/Epic) and build, in an issue.

If `recon list` finds nothing, the vtable RVA may differ for your build: run
`odradek-sync recon discover` (needs numpy) and compare with `config/games/death_stranding_dc.toml`.

## A new game build (or Steam vs Epic)

1. `odradek-sync recon discover` with the game running. It finds resource-path strings,
   pointers to them, and the vtable they belong to (about a minute). The top candidate gives
   `vtable_rva`, `name_offset` and the likely `state_offset`.
2. Copy `config/games/death_stranding_dc.toml` to e.g. `death_stranding_dc_steam.toml`, change
   `id`, the offsets, and `verified_builds`, and copy the signal map under the new id.
3. Run with `--game death_stranding_dc_steam`, and check with `recon list --active`.

## The player app and releases

The downloadable builds wrap `odradek-sync-app` (`src/odradek_sync/app/`), a deliberately small
entry point. It differs from the developer CLI in these ways:
- **It only runs the game → keyboard service.** No recon, demos or status lines; the spec
  excludes `recon` and `cli`.
- **Plain-language log only** (`app/userlog.py`). New messages should be one short sentence a
  non-technical player understands, logged once per situation (`UserLog.once`). Never log game
  states, signals or animation names there. Use `odradek-sync run` for that.
- **It keeps going.** `ResilientKeyboard` retries when OpenRGB is missing or closed, or the
  keyboard is unplugged. Game attach status comes from `SyncEngine(on_status=...)`.
- **Switching lighting backends live** (`ResilientKeyboard.switch`): the new backend is opened on
  a worker thread while the current one keeps showing, and only swapped in once it opened. A
  failure in its first `SWITCH_GRACE` seconds brings the previous backend back. The tray offers
  the backends in `lighting.BACKEND_LABELS`, greyed out while `lighting.backend_status()` says
  why one can't be used (re-checked every 10 s).
- **One instance, graceful stop:** a lock file plus a stop-request file (`app/instance.py`),
  the same on both OSes. `--stop`, `--open-log`, `--open-settings`, `--uninstall`.
- **Tray** (`app/tray/`): the menu is one data model (`menu_items`) shared by the backends.
  - Linux: `sni.py` speaks StatusNotifierItem + dbusmenu over D-Bus with jeepney, so there's no
    GTK/Qt dependency.
  - Windows: `win.py` uses pystray, and is untested.
  - Clicks become action names on a queue, handled on the main thread. No tray = `NullTray`.
  - To inspect the Linux tray: `busctl --user call org.kde.StatusNotifierItem-<pid>-1 /MenuBar
    com.canonical.dbusmenu GetLayout iias -- 0 -1 0`.
- **Settings and autostart:** `settings.toml` is created with comments on first run.
  Autostart (XDG entry / HKCU Run key) and the Linux menu entries are re-synced on every launch.

Building:

| | Command | Output |
| --- | --- | --- |
| Linux | `bash packaging/build_linux.sh` | `dist/OdradekSync-<version>-x86_64.AppImage` |
| Windows | `packaging\build_windows.ps1` (needs Inno Setup 6) | `dist\OdradekSync-<version>-setup.exe` |

Both run PyInstaller with `packaging/odradek-sync.spec` (onedir; no console window on Windows)
and generate the icon with `packaging/make_icons.py`, so the repo holds no binaries.
PyInstaller can't cross-compile, so each OS builds its own.

**Releasing:** see [RELEASING.md](RELEASING.md) for the version rules, the changelog standard,
config format versions and the step-by-step release process. In short: run
`python scripts/release.py prepare X.Y.Z`, commit, then push a `vX.Y.Z` tag. CI checks the tag
against `pyproject.toml`, builds both apps, and makes a draft release.

## Pull request checklist

- [ ] tests pass: `python -m unittest discover -s tests`
- [ ] a line under `## [Unreleased]` in `CHANGELOG.md` for any user-visible change, written for
      players, with ⚠️ if users must do something ([RELEASING.md](RELEASING.md#changelog))
- [ ] new knowledge (offsets, animation names, effect choices) is in TOML, not Python
- [ ] a config structure change bumps that kind's `format` ([RELEASING.md](RELEASING.md#config-format-versions))
- [ ] new player-facing log lines are one plain sentence

## Ground rules

- **Never write to game memory**, not even "harmless" test writes. Platform backends open
  processes read-only.
- **Never send guessed packets to devices.** Vendor HID channels (like the AULA keyboard's
  Bluetooth/2.4 GHz channel) can brick firmware. Only use documented protocols, or ones captured
  from the vendor's own software.
- **Keep knowledge in data.** If you're writing an animation name or an offset in Python, it
  probably belongs in a TOML file.
- **Tests:** add unit tests with `tests/fakes.py` (a fake process laid out like the game) and
  the console/null devices. No hardware or game in CI.
- **Always pass `encoding="utf-8"`** to `open()`, `read_text()` and `write_text()`. Windows
  defaults to cp1252, which can't read files like `CHANGELOG.md`. The tests run with
  `-X warn_default_encoding -W error::EncodingWarning`, so a missing encoding fails CI on Linux too:
  `python -X warn_default_encoding -W error::EncodingWarning -m unittest discover -s tests`
- **Style:** Python 3.11+, type hints, small modules. Docstrings should explain what and why;
  the code shows how.
