"""Small shared helpers: colours, timestamps, per-user directories."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RGB = tuple[int, int, int]
Color = tuple[float, float, float]
BLACK: Color = (0.0, 0.0, 0.0)


def parse_color(value) -> Color:
    """'#rrggbb' or [r, g, b] -> (r, g, b) floats in 0..255."""
    if isinstance(value, str):
        v = value.lstrip("#")
        if len(v) != 6:
            raise ValueError(f"colour must be #rrggbb, got {value!r}")
        return (float(int(v[0:2], 16)), float(int(v[2:4], 16)), float(int(v[4:6], 16)))
    r, g, b = value
    return (float(r), float(g), float(b))


def scale(c: Color, k: float) -> Color:
    return (c[0] * k, c[1] * k, c[2] * k)


def mix(a: Color, b: Color, k: float) -> Color:
    return (a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k)


def to_rgb(c: Color) -> RGB:
    return (max(0, min(255, int(c[0]))), max(0, min(255, int(c[1]))), max(0, min(255, int(c[2]))))


def stamp(t: float | None = None) -> str:
    t = time.time() if t is None else t
    return time.strftime("%H:%M:%S", time.localtime(t)) + f".{int(t % 1 * 1000):03d}"


def user_config_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "odradek-sync"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "odradek-sync"


def user_cache_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "odradek-sync" / "cache"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "odradek-sync"


def user_log_dir() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "odradek-sync"
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "odradek-sync"
