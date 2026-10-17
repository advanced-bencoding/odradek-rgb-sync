"""Reference keyboard layouts, for keyboards that don't report a key matrix.

Positions are key centres in key units (1 = one standard key width), rows 0 (F-row) to 5 (space
bar row), following an ANSI board. Key ids are OpenRGB's LED names, lower-cased, without the
"Key: " prefix ("escape", "f1", "number pad 7", "\\ (ansi)"). `canonical()` also accepts common
alternatives ("Esc", "LCtrl", "PgUp", "Numpad 7").

Five size classes: full (with number pad), tkl (tenkeyless), 75 (F-row, compact nav column),
65 (no F-row, arrows) and 60 (no F-row, no arrows). They're told apart by which keys exist
(`classify_by_keys`), or, when names are unusable, by LED count (`classify_by_count`).
"""
from __future__ import annotations

import re

SIZES = ("full", "tkl", "75", "65", "60")
SIZE_LABEL = {"full": "full-size", "tkl": "tenkeyless", "75": "75%", "65": "65%", "60": "60%"}

Pos = tuple[float, float]


def _row(y: float, keys: list[tuple[str, float]]) -> dict[str, Pos]:
    return {k: (x, y) for k, x in keys}


_ALNUM = {
    **_row(1, [("`", 0.5)] + [(str((i + 1) % 10), 1.5 + i) for i in range(10)]
           + [("-", 11.5), ("=", 12.5), ("backspace", 14.0)]),
    **_row(2, [("tab", 0.75)] + [(k, 2.0 + i) for i, k in enumerate("qwertyuiop")]
           + [("[", 12.0), ("]", 13.0), ("\\ (ansi)", 14.25)]),
    **_row(3, [("caps lock", 0.875)] + [(k, 2.25 + i) for i, k in enumerate("asdfghjkl")]
           + [(";", 11.25), ("'", 12.25), ("# (iso)", 13.25), ("enter", 13.875)]),
    **_row(4, [("left shift", 1.125), ("\\ (iso)", 1.75)] + [(k, 2.75 + i) for i, k in enumerate("zxcvbnm")]
           + [(",", 9.75), (".", 10.75), ("/", 11.75)]),
    **_row(5, [("left control", 0.625), ("left windows", 1.875), ("left alt", 3.125), ("space", 6.875)]),
}

FULL: dict[str, Pos] = {
    **_ALNUM,
    **_row(0, [("escape", 0.5)] + [(f"f{i + 1}", x) for i, x in enumerate(
        [2.5, 3.5, 4.5, 5.5, 7.0, 8.0, 9.0, 10.0, 11.5, 12.5, 13.5, 14.5])]
        + [("print screen", 15.75), ("scroll lock", 16.75), ("pause/break", 17.75)]),
    **_row(1, [("insert", 15.75), ("home", 16.75), ("page up", 17.75), ("num lock", 19.0),
               ("number pad /", 20.0), ("number pad *", 21.0), ("number pad -", 22.0)]),
    **_row(2, [("delete", 15.75), ("end", 16.75), ("page down", 17.75), ("number pad 7", 19.0),
               ("number pad 8", 20.0), ("number pad 9", 21.0)]),
    "number pad +": (22.0, 2.5),
    **_row(3, [("number pad 4", 19.0), ("number pad 5", 20.0), ("number pad 6", 21.0)]),
    **_row(4, [("right shift", 13.625), ("up arrow", 16.75), ("number pad 1", 19.0),
               ("number pad 2", 20.0), ("number pad 3", 21.0)]),
    "number pad enter": (22.0, 4.5),
    **_row(5, [("right alt", 10.625), ("right windows", 11.875), ("right fn", 11.875), ("left fn", 11.875),
               ("menu", 13.125), ("right control", 14.375), ("left arrow", 15.75), ("down arrow", 16.75),
               ("right arrow", 17.75), ("number pad 0", 19.5), ("number pad .", 21.0)]),
}

NUMPAD = {k for k in FULL if k.startswith("number pad") or k == "num lock"}
NAV = ["print screen", "delete", "insert", "home", "page up", "page down", "end"]
ARROWS = {"up arrow", "down arrow", "left arrow", "right arrow"}
FROW = {f"f{i}" for i in range(1, 13)}


def _compact(with_frow: bool, with_arrows: bool, present: set[str]) -> dict[str, Pos]:
    """75%, 65% and 60% boards: one nav column at the right edge, arrows tucked under it."""
    t = dict(_ALNUM)
    if with_frow:
        t.update(_row(0, [("escape", 0.5)] + [(f"f{i + 1}", 1.5 + i) for i in range(12)]))
    else:
        t["escape"] = (0.5, 1.0)   # no F-row: Esc takes the ` position
    if with_arrows:
        t.update(_row(4, [("right shift", 12.875), ("up arrow", 14.5)]))
        t.update(_row(5, [("right alt", 10.5), ("right windows", 11.5), ("right fn", 11.5), ("left fn", 11.5),
                          ("menu", 11.5), ("right control", 12.5), ("left arrow", 13.5),
                          ("down arrow", 14.5), ("right arrow", 15.5)]))
        # stack whichever nav keys exist in the right column, bottom-aligned to row 4
        nav = [k for k in NAV if k in present and (with_frow or k != "print screen")]
        top = 0 if with_frow else 1
        first = max(top, 5 - len(nav))
        for i, k in enumerate(nav[: 5 - top]):
            t[k] = (15.5, float(first + i))
    else:
        t.update(_row(4, [("right shift", 13.625)]))
        t.update(_row(5, [("right alt", 10.625), ("right windows", 11.875), ("right fn", 11.875),
                          ("left fn", 11.875), ("menu", 13.125), ("right control", 14.375)]))
    return t


TYPICAL_COMPACT_NAV = {"delete", "page up", "page down", "end"}


def template(size: str, present: set[str] | None = None) -> dict[str, Pos]:
    """Reference positions for a size. `present` (the board's keys) decides which nav keys fill
    the compact boards' right column; without it, a typical Delete/PgUp/PgDn/End column."""
    present = present if present is not None else (set(FULL) if size in ("full", "tkl") else TYPICAL_COMPACT_NAV)
    if size == "full":
        return dict(FULL)
    if size == "tkl":
        return {k: v for k, v in FULL.items() if k not in NUMPAD}
    if size == "75":
        return _compact(True, True, present)
    if size == "65":
        return _compact(False, True, present)
    if size == "60":
        return _compact(False, False, present)
    raise ValueError(f"unknown size {size!r}")


def classify_by_keys(keys: set[str]) -> str:
    if len(keys & NUMPAD) >= 6:
        return "full"
    frow = len(keys & FROW) >= 8
    arrows = len(keys & ARROWS) >= 3
    # a tenkeyless board has the whole 3x2 nav cluster plus Scroll Lock/Pause; 75% boards don't
    if frow and {"insert", "home", "page up"} <= keys and keys & {"scroll lock", "pause/break"}:
        return "tkl"
    if frow:
        return "75"
    return "65" if arrows else "60"


def classify_by_count(n: int) -> str:
    if n >= 100:
        return "full"
    if n >= 86:
        return "tkl"
    if n >= 75:
        return "75"
    if n >= 66:
        return "65"
    return "60"


_ALIASES = {
    "esc": "escape", "return": "enter", "bksp": "backspace", "back space": "backspace",
    "caps": "caps lock", "capslock": "caps lock", "spacebar": "space", "space bar": "space",
    "pgup": "page up", "pageup": "page up", "pgdn": "page down", "pagedown": "page down",
    "del": "delete", "ins": "insert", "prtsc": "print screen", "printscreen": "print screen",
    "print scr": "print screen", "scrlk": "scroll lock", "pause": "pause/break", "break": "pause/break",
    "\\": "\\ (ansi)", "backslash": "\\ (ansi)", "fn": "right fn", "app": "menu", "apps": "menu",
    "context menu": "menu", "up": "up arrow", "down": "down arrow", "left": "left arrow",
    "right": "right arrow", "grave": "`", "tilde": "`", "numlock": "num lock",
}
_SIDE = re.compile(r"^(l|r|left|right)[ _-]?(ctrl|control|shift|alt|win|windows|super|gui|cmd|meta|fn)$")
_PAD = re.compile(r"^(?:number pad|numpad|num pad|num|kp|keypad)[ _-]?(.+)$")
_SIDE_NAME = {"ctrl": "control", "control": "control", "shift": "shift", "alt": "alt", "fn": "fn",
              "win": "windows", "windows": "windows", "super": "windows", "gui": "windows",
              "cmd": "windows", "meta": "windows"}


def canonical(name: str) -> str | None:
    """OpenRGB LED name (or a common variant) -> key id in FULL, or None if it isn't a known key."""
    k = re.sub(r"\s+", " ", name.strip().lower())
    for prefix in ("key: ", "key ", "key_"):
        if k.startswith(prefix):
            k = k[len(prefix):]
    k = _ALIASES.get(k, k)
    m = _SIDE.match(k)
    if m:
        side = "left" if m.group(1) in ("l", "left") else "right"
        k = f"{side} {_SIDE_NAME[m.group(2)]}"
    m = _PAD.match(k)
    if m and k not in FULL:
        rest = {"enter": "enter", "plus": "+", "minus": "-", "slash": "/", "star": "*", "asterisk": "*",
                "period": ".", "dot": ".", "del": ".", "decimal": "."}.get(m.group(1), m.group(1))
        k = f"number pad {rest}"
    return k if k in FULL else None
