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

## Open questions

| Question | Notes |
| --- | --- |
| Static orange while BTs follow you | Both warning animations stop. Find the animation with `recon watch` + markers. |
| Red | Never captured (it needs a BT grab or a fight). |
| Orange spin speed, blue pulse speed as a number | Rapid vs slow spin changes no animation, so it's probably a playback-rate float or the distance to the nearest BT. That needs the step 1 technique, scanning for a float that rises or falls as BTs get closer. |
| Windows | The backend is written but untested. Load addresses differ from Proton, but the RVA-based lookup should not care. |
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
