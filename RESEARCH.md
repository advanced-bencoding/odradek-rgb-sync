# Research log: from "can we read the Odradek?" to named animations

This is how odradek-sync's approach was found, including the dead ends. The work was done on
*Death Stranding Director's Cut* (Epic Games Store build), running under GE-Proton on Fedora 44
through the Heroic launcher.

## The goal and the constraint

The aim was to transmit the Odradek's status as you play: its colour (folded, blue, orange,
red) and its variants (slow vs rapid flashing, spinning vs static). The one hard rule was **no
screen reading**. The status had to come from the game itself.

There's no telemetry API, mod loader or public Cheat Engine table that covers the Odradek. The
public DS:DC tables cover movement and stats only. That left reading the game's memory.

## Step 0: can we read the process at all?

Under Proton the game is an ordinary Linux process (`DeathStranding.exe` in its command line),
nested inside Heroic's Flatpak and Steam's pressure-vessel sandbox. With
`kernel.yama.ptrace_scope = 0`, `/proc/<pid>/mem` is readable as the normal user, through both
sandboxes, without root. `/proc/<pid>/maps` lists the regions, and the Windows executable shows
up mapped from its file path, so its load address is easy to find. Nothing is ever written.

## Step 1: differential scanning (Cheat Engine style)

The method: take labelled snapshots of all writable memory (about 4 GB) while the player
describes the Odradek ("blue, rapid flashing", "orange, rotating"). Keep only values that are
constant within a label and different between labels, interpreted as u8 (any offset), u32 and
f32 (4-byte aligned).

What we learned building it:
- **Snapshots must be taken close together in the world.** The first two snapshots were taken
  far apart, and 371 million candidates survived (4.5 GB of candidate data). Restarting at the
  edge of one BT area started at 7 million.
- **Alternating between just two states only halves the list each time.** A third state, or a
  "hold" (re-reading all candidates for 15 s while the state stays steady and dropping anything
  that moves), cuts far deeper: 27.7K → 1.7K in two holds.
- **A NumPy trap:** `np.searchsorted(uint64_array, [python ints])` silently converts to float64
  and copies the whole array on every call. One snapshot hung for over 10 minutes until the
  keys were passed as `np.uint64` arrays.

This produced plausible but nameless results:

| Address (one session only) | Behaviour | Our guess then |
| --- | --- | --- |
| `0x1e44518b8` (u8) | blue = 3, orange = 2, but folded also 2 | colour flag |
| `0x1cdd8cd78` (u8) | 2, blipping to 3 for ~0.27 s; held at 3 during rapid blue | flash phase |
| `0x5cee793dc2c` (f32) | 1.0/0.0, toggling during spinning orange | spinning |

Every address changed with each game launch, and the colour byte couldn't tell orange from
folded. It worked, but it was fragile.

## Step 2: recordings + controller timestamps

To test events rather than states, we recorded every byte change in ±1 MiB windows around the
candidates at ~35–40 samples per second. At the same time we logged controller presses through
evdev, read-only: the Xbox pad is readable through a logind ACL, so no root and no grabbing the
device. With the player pressing RB (terrain scan) in pairs:

- A byte next to the flash byte went 2 → 3 for ~0.46 s, starting 0.19–0.24 s after each
  accepted press: **6 out of 6**. Presses during the cooldown produced nothing, and nothing
  fired without a press. We called it "terrain scan, confirmed".
- An idle control recording (2 minutes of running around and opening the map, no BTs) changed
  none of the mapped bytes, and gave a baseline of "bytes that change anyway".

## Step 3: contradictions

Entering a BT zone broke the model:
- The "scan" byte turned on for **5.5 s with no RB press**, about 13 s after entering the zone.
- Pressing RB inside the BT zone **didn't touch the scan byte**. A different byte nearby pulsed
  instead, for ~1.1 s.
- All the interesting bytes used the same few values (2, 3, sometimes 4), and their addresses
  were all multiples of `0xA0` (160 bytes) apart.

Dedicated flags don't move between addresses. This looked like an **array of same-sized
objects**, each with a little state machine, where different objects light up for different
things.

## Step 4: object anatomy

Dumping the bytes in front of each state byte showed the same shape every time:

```
+0x00  0x6ffff00d2968    identical in every object, and points into DeathStranding.exe
+0x08  16 random bytes   unique per object
+0x18  2 / 3 / 4         the byte we had been tracking
+0x20  0x6ffff00d29d0    another pointer into the exe (an embedded sub-object's vtable)
+0x28  pointer           -> "ds/animations/game/odra/odra/an_odra_arm_search"
```

- **`+0x00`:** a pointer that's identical across objects and points into the executable image
  is a C++ **vtable**, so these are all objects of one class.
- **`+0x08`:** vtable-then-GUID is how Decima (the game's engine) lays out its reference-counted
  objects, and each GUID appeared exactly once in memory.
- **`+0x28`:** following each 8-byte value to see whether it pointed at text gave the **resource
  path**.

Searching all of memory for that vtable value (exe base + `0x3C12968`) found **7,779 animation
resource objects**, every one with a name. About 145 are the Odradek's (`odra/odra/an_odra_*`),
and more belong to BB, Sam and others. Every byte from steps 1–3 turned out to be one of them:

| What we thought | What it actually is |
| --- | --- |
| colour flag (blue = 3) | `bbyface_r_scared_lp`: **BB's scared face** |
| "folded" / "unfolding" | BB's `def_q_idle_lp` / `scared_st` |
| flash phase | `odra_main_warrning_sign_lp`: the Odradek's warning-light loop |
| terrain scan (outside BT zones) | `odra_main_wakeup`: the folded Odradek waking up |
| the other byte that pulsed in the BT zone | `odra_arm_search` + `odra_main_search`: the real scan |
| unnamed byte at entry | `odra_main_gzm_on_spin` |

The field at `+0x18` is the animation's **play state**: 2 = idle, 3 = playing, 4 = held (as
with `sleep_lp` while folded).

This changed the approach entirely:
- **Addresses no longer need to be stored.** Each launch: find the exe, add the vtable RVA,
  search for that value, read the names. That's about 20 s for 4 GB, and it's done once.
- **Mapping became reading names.** A watcher prints "animation X started / stopped" while the
  player narrates.

## Step 5: mapping by name

With named animations, the rest went quickly. Each finding below was checked against the
player's description and against logged button presses.

- **Colour = which warning animation plays.** Blue is `odra_main_warrning_sign_lp`; orange is
  `odra_main_warrning_sign_near_lp`. They swap in the same frame. During orange, BB switches to
  `crying_small_loop_lp` and `bbydef_q_search_*`.
- **Blue pulse speed comes from timing.** When rapid, the blue animation stays on continuously.
  Slower pulsing switches it on for ~0.27 s every **~1.8 s** (medium range) or **~3.3 s**
  (BTs far), with `odra_main_idle_lp` playing in between. The `pulse_rate` deriver turns this
  into `rapid / fast / slow`, using the median of the last three intervals so one missed flash
  doesn't flip it.
- **Folded is `sleep_lp` in play state 4.** It reads 3 while open.
- **Terrain scan is `search` everywhere.** Re-reading the first RB recording with the new names
  showed that a folded scan is `wakeup` (0.5 s) → `search` (1.1 s) → back to folded about 3 s
  later, 6/6. Inside a BT zone and during autotoxemia, scans play `search` alone.
- **Autotoxemia** is `odra_main/arm_autointoxication_lp`. It started after the cutscene that
  plays when BB gets overwhelmed, and scans still play over it.
- **Leaving a BT zone** shows up as BB going from scared to idle, with the last blue pulse at
  the same moment.

## Step 6: corrections from real play

Running the keyboard live exposed two mistakes in the mapping:
- **BB's autotoxemia isn't the Odradek's.** At first, autotoxemia included BB's
  `bbydef_q_autointoxication_lp`. During play, that animation came on **alone** while the
  Odradek kept pulsing slow blue, and the keyboard showed autotoxemia wrongly. The signal now
  uses only the Odradek's animations; BB's is a separate, weak signal.
- **"BTs following your footprints" is a separate, unmapped state.** After orange, when BTs
  follow you, both warning animations stop, while the in-game Odradek shows a static orange.
  The keyboard fell back to "open, nothing around". Some other animation must be playing; it's
  listed under `[unmapped]` in the signal map, and the recon workflow in CONTRIBUTING.md is how
  to find it.

## Step 7: the keyboard

The keyboard is an AULA F75. OpenRGB supports it over **USB only** (`258a:010c`, Sinowealth
protocol): 90 LEDs on a 6×15 matrix, in Direct mode, comfortably at 30 fps. Its other two
connections show up as different devices:
- **Bluetooth:** `3554:fa08`
- **2.4 GHz dongle:** `3554:fa09`

Both have only a vendor HID channel (usage page `0xFF02`, report `0x13`, 19-byte packets) with
an undocumented format. We deliberately didn't probe it: guessing commands on Sinowealth parts
can change saved settings or drop the board into firmware-update mode. Wireless lighting would
need the protocol captured from AULA's own software, if that software can do it at all.

Later, on Windows with OpenRGB 1.1.0 installed as a service: while OpenRGB has the AULA F75 in
Direct mode, the keyboard ignores its own lighting styles and the knob press that cycles them.
OpenRGB puts it in Direct whenever it detects it, so after every boot and every replug, with no
client connected; stopping the service freed it. The keyboard's OpenRGB modes are only Off and
Direct, but **Off hands the lighting back to the keyboard's firmware**: the knob works again, with
the service still running. So Odradek Sync takes the keyboard (Direct) only while the game runs
and switches it to Off otherwise; the device file says so (`[openrgb] release_mode`).

## Step 8: making it portable

The research scripts became this repository. Game knowledge (offsets, animation names, signal
meanings, evidence) and lighting choices (effects, regions) moved into TOML, behind interfaces
for platforms, lighting backends, layouts and effects.

One more check: `recon discover` re-derives the object layout from scratch. It finds path
strings, pointers to them, and the vtable in front of each pointer. On the live game it ranked
`vtable_rva = 0x3C12968`, `name_offset = 0x28`, `state_offset = 0x18` first: that state slot
held a small integer in 92% of 1,343 sampled objects. The embedded sub-object's vtable came
second with the same count, as expected. So a new game build can be supported without redoing
steps 1–4.

## Step 9: Windows and the standard edition

The first run on native Windows (Windows 10, *Death Stranding* standard edition 1.0.8 from the
Epic Games Store, same executable name `DeathStranding.exe`) found two things:

- **Only the vtable moved.** `recon discover` found the animation class at
  `vtable_rva = 0x38703C0` (Director's Cut: `0x3C12968`), with the same `name_offset = 0x28`,
  `state_offset = 0x18` (99% small integers) and the embedded sub-object's vtable at `+0x68`,
  just as in the DC. Every one of the 26 animations the signal map uses exists under the same
  name, and a folded terrain scan played `wakeup` → `search` → `sleep_lp` as documented in step 5.
  So one game profile lists both RVAs. The exe has no RTTI, so the build is told apart by which
  vtable finds named objects. At the DC's RVA, the standard exe has no vtable at all.
- **Half of the writable memory is the GPU's.** About 3.9 GiB of the game's 7.8 GiB writable
  memory is write-combined (D3D12 upload heaps and the like). Reading it ran at ~120 MiB/s and
  took 32 of the scan's 37 s of reads, and it never holds an animation object. Linux already
  skipped device mappings; Windows now skips `PAGE_WRITECOMBINE` and `PAGE_NOCACHE` pages.

A second, cross-platform speedup came from the search itself. `bytes.find` skips ahead by the
needle's last byte, and a little-endian user-space pointer ends in `0x00`, the most common byte
in memory. Searching for the pointer's low 4 bytes and then checking all 8 ran 3.2× faster
(239 → 758 MiB/s) and found the same objects. Together, the first scan on Windows went from
87 s to about 15 s.

## Step 10: caught in the tar

Two recordings of every animation (`recon watch --all`) in the first BT area of the standard
edition, each covering one capture, with the player narrating afterwards: rapid blue, then orange
spinning; "right when the BT detects us, the Odradek goes static, pointing towards the BT"; when
the tar forms, "one wing is orange, the others blue, and it tracks the tar creatures"; escape to
rapid blue. Both recordings line up the same way:

| Moment | Animations |
| --- | --- |
| Orange (4.3–4.5 s) | `odra_main_warrning_sign_near_lp` |
| A BT detects Sam | **`odra_main_surprise` + `odra_arm_surprise`** for 2.2 s, starting in the frame orange stops |
| The tar forms, 2.7–3.8 s later | `gzmcrd_s_idle_lp` (BT cords) drops from 18–21 to 7; `gzncrd_s_idle_lp` to 2 |
| In the tar, 22–28 s | **no warning animation**; the Odradek points (`point_lp`, forward and crouch poses); BB's heavy crying bursts (`bbydef_q_crying_st/lp/lp2/ed`, `bbyface_r_def_q_crying_start/loop/end_lp`) |
| Escape | BB gets scared again, the cords count back up, blue returns |

None of the ~975 loaded animation names mentions tar, dragging or grabbing, so the tar itself has no
animation in this class. The names did confirm that `gzm` is the gazer (BT): `gzmcrd` is its
cord, and there are cord-cutting (`hcufdef_samgzm_*_stealth_attack`, `gzmcrd_s_dam_stealth_attack`)
and bola takedown (`blgrop_gzm_boladown_*`) animations to map later.

So `bt_detected` maps the surprise, and `tar` is a `latch` held from it until a warning light (or
folding) ends it, with a 60 s limit. Replaying both recordings through the signal map turns `tar` on
exactly at each detection and off at each escape, and nowhere else. This is very likely what step 6
noted on the Director's Cut as "static orange while BTs follow your footprints": both warning
animations stop after orange.

Two side findings: the play-state field isn't a play state for every animation. Ones shared by many
characters count up instead (BT cords 7–21, other porters' faces 22–26), so for those it's probably
a reference count. And on Windows, switching away from the game pauses it, which shows up in a
recording as nothing changing.

## Step 11: telling paused from playing

Pausing freezes every animation state, but so, almost, does standing still: in the BT-zone
recordings the tracked animations went up to 7.1 s without a change (Sam's face alone 14.8 s), so
waiting for a freeze would react late and misfire. The game has to say it's paused.

Method: sample the exe's writable sections (56.6 MiB, 185 regions) twice a second as u32 slots,
storing only changes, together with whether the game window has focus, while the player plays
and pauses on cue (pause menu twice, then alt-tab). The phases were obvious from memory activity
alone: 10,000–25,000 slots changed per tick while playing, ~180 while paused. Then look for slots
that hold one value through every pause and another through play (flags), or change on nearly
every play tick and never while paused (clocks).

Of 634,278 slots that changed at all, the clearest is a timer block at RVA `0x44E2320` (standard
edition 1.0.8): a running game clock, a frame step of 0.0167 s at `+0xC`, and at `0x44E2424` an f32
**speed: 1.0 while playing, 0.0 while paused**. It flipped in the same half-second as the activity
at all six boundaries, and stayed 0 through the alt-tab: the game uses one pause for the menu and
for losing focus. A u32 at `0x5108228` (1 while paused) flipped with it, with heap pointers filling
its neighbours, so it looks like the pause menu's state; the speed was chosen because "the game
clock is stopped" is the definition of paused.

The profile keeps this per build (`[[game_speed]]`, keyed by the build's vtable RVA), and while
the speed is 0 the engine shows the no-game look and stops the derived signals' clock, so a pause
in the tar doesn't use up `tar`'s 60 s limit. The first live run reported `paused` at once.

## Open questions

| Question | Notes |
| --- | --- |
| How many BTs are near | `gzmcrd_s_idle_lp` counts BT cords (7 → 21 as BTs appeared, see step 10). A deriver could turn it into a level, but its baseline may differ per area. |
| The tar's colours | One wing orange, the rest blue, tracking the creatures in the tar: not an animation state. Probably a material parameter. |
| Pause on the Director's Cut | Its game speed address isn't known; step 11's method finds it. |
| Dragged to a big BT | `cst_small/middle/big_born` (likely the big BT rising) never played; Sam escaped both times. |
| Red | Never captured (it needs a BT grab or a fight). |
| Orange spin speed, blue pulse speed as a number | Rapid vs slow spin changes no animation, so it's probably a playback-rate float or the distance to the nearest BT. That needs the step 1 technique, scanning for a float that rises or falls as BTs get closer. |
| Steam build, patches | The vtable RVA may differ; `recon discover` should handle it. |
| BB's solo autotoxemia | What it means (stress level?) is unknown. |

## Milestones

1. The game's memory is readable through Proton and Flatpak. First differential scans: 371M
   candidates, then restarted at 7M by staying in one place.
2. Colour, flash and spin candidates; a minute-long recording with the player's narration.
3. Terrain scan "confirmed" against logged RB presses (6/6).
4. A recording of entering a BT zone: the scan byte fires without RB, and the model breaks.
5. The objects identified: vtable + GUID + play state + resource path; 7,779 named animations.
6. Colour, pulse speed, folded, autotoxemia and the scan mapped by name.
7. Effects on the AULA F75 through OpenRGB; live keyboard mode.
8. Corrections from real play: BB-only autotoxemia; "BT following" found to be unmapped.
9. This repository; `recon discover` re-derives the layout on the live game.
10. Native Windows and the standard edition 1.0.8: same layout, different vtable RVA; GPU memory
    skipped; first scan 87 s → ~15 s.
11. Caught in the tar: the BT detecting Sam (`surprise`) and the tar held until the warning light
    returns; BT cord counts found.
12. Pause: the game's speed (0 while paused) found in the exe's data; the keyboard rests while paused.
