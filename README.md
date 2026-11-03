# Odradek RGB Sync

Mirror the **Odradek** from *Death Stranding* (standard edition or Director's Cut) on your RGB
keyboard, live, while you play. It shows the blue warning flashes, spinning orange when a BT is close, the terrain-scan
pulse, autotoxemia, and BB's mood.

There's no screen capture and no game mod. odradek-sync **reads** the game's memory, never
writes it, and watches which of the game's own animations are playing. The Odradek's warning
light, for example, is an animation called `an_odra_main_warrning_sign_lp`. When it plays, your
keyboard flashes blue. [RESEARCH.md](RESEARCH.md) explains how we found that out.

```
game memory ──► animation states ──► signals ──► effect map ──► keyboard
 (read-only)    odra_main_search=3    scan=true    shockwave      (OpenRGB)
```

## For players: download and run

You don't need Python or a terminal.

1. **Install [OpenRGB](https://openrgb.org)** and check that it sees your keyboard. Plug the
   keyboard in with its USB cable; wireless modes usually can't be controlled. On an **ASUS ROG
   Flow Z13 (2025)** running Linux, install [z13ctl](https://github.com/dahui/z13ctl) instead (see
   [ASUS ROG Flow Z13](#asus-rog-flow-z13-2025)); Odradek Sync detects the Z13 by itself. The Z13
   isn't supported on Windows.
2. **Get Odradek Sync** from the [releases page](../../releases):
   - **Windows:** run `OdradekSync-<version>-setup.exe`. No admin rights needed. It adds "Odradek
     Sync", "Stop Odradek Sync", "Odradek Sync log" and "Odradek Sync settings" to the Start menu.
   - **Linux:** download `OdradekSync-<version>-x86_64.AppImage`, make it executable
     (right-click → Properties → "Allow executing", or `chmod +x`), and double-click it. It adds
     the same entries to your application menu.
3. **Play.** Odradek Sync runs in the background, starts OpenRGB if needed, waits for Death
   Stranding, and starts again automatically when you log in. It only takes over the keyboard
   while the game runs: before and after, the keyboard has its own lighting (on the AULA F75,
   including the knob that changes its style).

**The tray icon** is greyed out while it's waiting, and in full colour once both the game and the
keyboard are connected. Its menu shows the status and lets you:
- switch **Subtle mode** on and off (applies immediately)
- toggle **Start at login**
- choose the **Lighting** software: OpenRGB, or z13ctl on an ASUS ROG Flow Z13 (Linux only). An option is
  greyed out, with the reason, until its software is installed and finds your hardware. Switching
  happens live; if the new one can't be opened, or stops working in its first seconds, Odradek
  Sync goes back to the previous one and says why in the log
- open the log or settings
- **Quit**

On Linux it uses the standard StatusNotifierItem tray (KDE Plasma and most desktops; GNOME
needs the AppIndicator extension). Without a tray, the app works the same and the menu entries
still work.

**The log** ("Odradek Sync log" in the menu) says what it's doing in plain words. Each line
starts with the date and time:

```
Starting service (version 0.1.0)
Waiting for Death Stranding to start
Keyboard detected: AULA F75
Connected to Death Stranding
Death Stranding closed
Stopped service
```

If something's missing it says so, for example "OpenRGB is not installed..." or "No RGB keyboard
found in OpenRGB...". It keeps checking, so you can fix the problem without restarting it.

**Settings** ("Odradek Sync settings"): `subtle` for the accessibility mode, `autostart`,
`keyboard` to choose between several keyboards, and `lighting` (`auto`, `openrgb` or `z13` (Linux only); the
tray's Lighting entries set it). Restart Odradek Sync after editing.

**Good to know:**
- **Ubuntu and some other Linux distros** block reading other programs' memory by default. If
  the log says "permission denied", run `sudo sysctl kernel.yama.ptrace_scope=0` once (it lasts
  until reboot). Fedora and Arch allow it out of the box.
- **Windows** may warn about an unrecognised app (SmartScreen), because the builds aren't
  code-signed.
- **Linux AppImages need FUSE.** On a few distros that means installing `libfuse2`.
- **OpenRGB takes over some keyboards just by running.** The AULA F75, for one, ignores its own
  styles and its knob whenever OpenRGB has detected it, even with nothing lighting it, and OpenRGB
  installed as a service detects it at every boot. Odradek Sync hands such keyboards back (OpenRGB's
  Off mode) whenever the game isn't running, so leave Odradek Sync running and the knob works
  outside the game.
- **To remove it:** Windows: uninstall from Settings → Apps. Linux: run the AppImage with
  `--uninstall`, then delete the file.

## Status

| Area | Status |
| --- | --- |
| Linux, game under Proton/Wine | **Works.** Developed and tested on Fedora 44 + GE-Proton (Heroic, Epic build) |
| Windows, native | **Works.** Tested on Windows 10 with the standard edition 1.0.8 (Epic), the installed player app and the developer CLI, and an AULA F75 through OpenRGB. Help wanted with other setups |
| Player app | Linux AppImage and Windows installer both tested (on Windows 10: install, tray, start at login, following the game, uninstall) |
| macOS | Not supported (no memory backend) |
| Game build | Standard edition 1.0.8 and Director's Cut (October 2026), both Epic Games Store; detected automatically. Other builds may need `recon discover` |
| Lighting | OpenRGB (tested: AULA F75 over USB). Keyboards without explicit support get an automatic fallback layout. A terminal preview for development |
| ASUS ROG Flow Z13 (2025) | **Linux only**, through z13ctl's daemon, picked automatically. Written and unit-tested, **not tested on a Z13 yet**. Help wanted. Not supported on Windows (z13ctl is Linux-only, and OpenRGB doesn't support the Z13) |
| Mapped states | scan, waking, folded, blue (rapid/fast/slow), orange, BT detects you, caught in the tar, autotoxemia, BB scared/crying/searching; the game paused (standard edition only so far) |
| Not mapped yet | red, orange spin speed, how many BTs are near (see `odradek-sync signals`) |

## Install (developers)

Python 3.11+. Players should use the downloads above instead.

```bash
git clone <this repo> odradek-sync && cd odradek-sync
python -m venv .venv
.venv/bin/pip install -e ".[openrgb]"        # add ,recon for the research tools (numpy)
```

On Windows the venv's programs are in `.venv\Scripts\` (`.venv\Scripts\pip install -e ".[openrgb]"`,
then `.venv\Scripts\Activate.ps1`). Python from the Microsoft Store stub isn't enough: install it from
python.org or with `winget install Python.Python.3.12`.

For keyboard lighting, install [OpenRGB](https://openrgb.org). odradek-sync starts
`openrgb --server` itself if no SDK server is running. Keyboards usually need their **USB cable**
for OpenRGB control. Bluetooth/2.4 GHz modes rarely expose a supported protocol.

**Linux:** reading another process's memory needs ptrace permission. With
`kernel.yama.ptrace_scope = 0` it works as your normal user, including Proton games inside
Flatpak launchers. Check with `sysctl kernel.yama.ptrace_scope`.

**Windows:** run odradek-sync as the same user as the game (or as administrator).

## Use

```bash
odradek-sync effects demo            # preview every state on the keyboard, no game needed
odradek-sync effects demo --lighting console   # ...or in the terminal
odradek-sync run                     # follow the game (start it before or after the game; Ctrl+C stops)
odradek-sync run --subtle           # accessibility mode: gentle effects, no strobes (see below)
odradek-sync run --lighting none     # status lines only
odradek-sync run --record session.jsonl        # also log every animation/signal change
odradek-sync signals                 # what each signal means, and how sure we are
odradek-sync devices                 # lighting devices OpenRGB (or z13ctl, on a Z13) sees
```

`--lighting` defaults to `auto`: `z13` on an ASUS ROG Flow Z13 running Linux, `openrgb` everywhere else.

`run` waits for the game and for the Odradek's animations to load. It finds them once (about
20 s of scanning), caches their addresses, and re-finds them after a game restart or when an
area reloads. Typical CPU use is 1–3% of one core.

### Keyboard layout: BB on top, the Odradek everywhere else

```
┌─────────────────────────────────────────────┐
│ Esc  F1  F2  ...  F12                       │  ← BB (top row)
├─────────────────────────────────────────────┤
│ `  1  2  3  ...                             │
│ Tab  Q  W  E  ...                           │  ← the Odradek (every other key)
│ ...                                         │
│ Ctrl Win Alt     Space        ...  ← ↓ →    │
└─────────────────────────────────────────────┘
```

- **Top row = BB.** On the AULA F75 that's Esc and F1–F12. When BB has nothing to show (Odradek
  folded, or no game running), the top row goes transparent and shows the Odradek's effect like
  the rest of the board.
- **Every other key = the Odradek:** its state (folded, blue, orange, autotoxemia...) plus
  one-shot events (scan, unfolding). Events also reach the top row, but only while BB is
  showing nothing there. Otherwise the top row stays BB's.

The split is set in the effect map (`config/effects/default.toml` and `subtle.toml`): the `bb`
layer has `region = "top_row"`, and the `odradek` layers cover `"all"` with BB drawn on top.
Which keys count as `top_row` comes from the device: matrix row 0 by default, or as defined in
`config/devices/<device>.toml`. Change `region` to move BB elsewhere (for example `wasd` or
`arrows`, both defined for the AULA F75).

### What you'll see (default effect map)

**The Odradek (all keys except the top row):**

| In game | Keyboard |
| --- | --- |
| Odradek folded | dim amber breathing |
| Game paused (the pause menu, or another window in front) | very dim amber breathing; the top row too |
| No game running | the keyboard's own lighting (AULA F75, or a keyboard whose device file sets `release_mode`); otherwise very dim amber breathing |
| Odradek open, nothing around | steady dim amber |
| Terrain scan | icy-blue shockwave from the space bar (a gold ring first if it was folded) |
| Blue, slow / fast | a blue flash each time the in-game light flashes |
| Blue, rapid | fast blue strobe rippling across |
| Orange | orange radar sweep spinning around the board |
| A BT detects you (the Odradek freezes, pointing at it) | steady orange |
| Caught in the tar (one wing orange, the rest blue), until you escape | an orange wing sweeping over blue |
| Autotoxemia | dying red flicker, keys going dark |

**BB (top row):**

| BB | Keyboard |
| --- | --- |
| crying (during orange and in the tar) | blue drops over dim orange |
| scared (during blue) | jittery amber |
| getting scared | dimmer amber jitter |
| calm, Odradek open | steady teal |
| Odradek folded / no game | nothing of its own: shows the Odradek's effect |

### Accessibility mode

`--subtle` (on `run` and `effects demo/show`) uses the `subtle` effect map. It keeps the same layout (BB on the top row, the Odradek everywhere else) and changes how things look:
- **No harsh effects:** no strobes, flicker or random jitter. Rapid blue is a steady glow,
  autotoxemia is a slow red breath, scans are a soft ring, and BB's moods are slow fades.
- **Lower brightness**, capped at 45%.
- **Every LED fades** towards its new colour (0.35 s time constant), so even sudden state
  changes become gentle. That stays well under WCAG 2.3.1's limit of three flashes per second.

The brightness cap and smoothing come from an `[accessibility]` table, which any effect map can
use, including your own:

```toml
[accessibility]
max_brightness = 0.45   # 0..1, per channel
smoothing = 0.35        # seconds
```

### Keyboards without explicit support

You don't need to wait for your keyboard to be "supported". On startup odradek-sync works out
your keyboard's layout and logs what it chose (`odradek-sync devices` shows it too):

- **OpenRGB reports a key matrix** (most keyboards): exact positions.
- **No matrix, but keys have names:** it detects the size (60%, 65%, 75%, tenkeyless or
  full-size) from which keys exist, and places them on a matching reference layout.
- **No usable names:** it guesses the size from the number of LEDs. Effects still fill the board
  and BB still gets the top area, but individual keys may be slightly off.

On a 60% or 65% board there's no F-row, so BB uses the number row (with Esc) instead. Device
files in `config/devices/` are only needed to fine-tune this.

### ASUS ROG Flow Z13 (2025)

**Linux only.** z13ctl only runs on Linux, so a Z13 running Windows isn't supported: there the
tray shows the Z13 entry greyed out, "Linux only".

OpenRGB can't drive the Z13's lighting, so on a Z13 Odradek Sync goes through
[z13ctl](https://github.com/dahui/z13ctl) instead. It notices the Z13 by itself; there's nothing to
choose. Install z13ctl, run `sudo z13ctl setup` once, and turn on its service:
`systemctl --user enable --now z13ctl.socket`.

The Z13 keyboard is one colour across the whole board, and it can only run its own built-in
effects (steady, breathing between two colours, strobe, colour cycle). So the Z13 gets its own,
simpler effect map (`config/effects/z13.toml`; `z13_subtle.toml` for subtle mode): no per-key
effects and no BB row, but every Odradek state still has its own colour and rhythm. Until the game
starts, and when Odradek Sync stops, your keyboard goes back to the lighting you set in z13ctl. If
z13ctl puts your lighting back by itself (after sleep, or when you reattach the keyboard), Odradek
Sync takes over again within a few seconds.

Preview the Z13 look on any keyboard with `odradek-sync effects demo --effects z13`. The speeds of
the Z13's breathing and strobe are estimates until someone times them on a real Z13.

## Configuration

All game knowledge and every lighting choice is data, in TOML files:

| Kind | Shipped in `src/odradek_sync/config/` | Purpose |
| --- | --- | --- |
| `games/` | `death_stranding_dc.toml` | process names, object layout (vtable RVA, offsets), which animations to track |
| `signals/` | `death_stranding_dc.toml` | signal → animations, with confidence and evidence; derived signals |
| `effects/` | `default.toml` | layers of rules: signal conditions → effect + parameters; demo scenarios |
| `devices/` | `aula_f75.toml` | per-device named regions (e.g. which keys form the top row) |

To customise, copy a file into your user config dir (`~/.config/odradek-sync/<kind>/` or
`%APPDATA%\odradek-sync\<kind>\`) and edit it there, or pass `--config-dir DIR`. Files with the
same name take precedence. You can make a new effect map (`effects/mine.toml`) and use it with
`--effects mine`. Run `odradek-sync effects list` for the effects and their parameters.

## Mapping more of the Odradek

`odradek-sync recon` contains the tools used to map everything above. `recon watch` prints
animation changes live, and lets you type markers as things happen in-game. `recon capture` and
`recon compare` find animations that tell two states apart. `recon discover` re-derives the
object layout for a new game build. [CONTRIBUTING.md](CONTRIBUTING.md) walks through the workflow.

## Versions

Releases follow [Semantic Versioning](https://semver.org); 1.0.0 is the first full release. What changed in each one is in [CHANGELOG.md](CHANGELOG.md). [RELEASING.md](RELEASING.md)
describes the versioning rules and the release process.

## Safety and fair play

- **Read-only.** odradek-sync opens the game process for reading only and never writes to it.
- **Single-player focus.** Death Stranding has online features through the Epic Online
  Services SDK. We know of no anti-cheat in Death Stranding, and reading memory is passive, but nobody has
  verified this against any publisher policy. Use at your own discretion.
- **No guessing at hardware.** Lighting only goes through documented protocols (OpenRGB, and
  z13ctl's daemon on a ROG Flow Z13). We don't send experimental packets to vendor HID channels,
  which can corrupt keyboard firmware.

## License

[MIT](LICENSE) © 2026 Benjamin Joseph.

Death Stranding and the Odradek belong to Kojima Productions. This project isn't affiliated
with or endorsed by Kojima Productions, Sony Interactive Entertainment or 505 Games, and it
contains no game code or assets: only offsets and animation names observed at runtime.
