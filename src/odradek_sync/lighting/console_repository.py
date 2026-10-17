"""A virtual keyboard drawn in the terminal with 24-bit colour: develop and preview effects without hardware."""
from __future__ import annotations

import sys
import time
from collections.abc import Sequence

from ..util import RGB
from .device import DeviceInfo, DeviceRepository, LedInfo, LightingDevice, pick

# A 75% layout, 6 rows x 15 columns, LED index = position in reading order.
ROWS = [
    ["Esc", None, "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12", None],
    ["`", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-", "=", "Bksp", "Del"],
    ["Tab", "Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P", "[", "]", "\\", "PgUp"],
    ["Caps", "A", "S", "D", "F", "G", "H", "J", "K", "L", ";", "'", None, "Enter", "PgDn"],
    ["Shift", None, "Z", "X", "C", "V", "B", "N", "M", ",", ".", "/", "RShift", "Up", "End"],
    ["Ctrl", "Win", "Alt", None, None, None, "Space", None, None, None, "RAlt", "Fn", "Left", "Down", "Right"],
]


def _virtual_info() -> DeviceInfo:
    leds, matrix = [], []
    for row in ROWS:
        out = []
        for name in row:
            if name is None:
                out.append(None)
            else:
                out.append(len(leds))
                leds.append(LedInfo(len(leds), name))
        matrix.append(tuple(out))
    return DeviceInfo("console", "Console keyboard", "keyboard", tuple(leds), tuple(matrix))


class ConsoleDevice(LightingDevice):
    def __init__(self, info: DeviceInfo, fps: float = 15, stream=None):
        self.info, self.min_dt, self.stream = info, 1 / fps, stream or sys.stdout
        self._last, self._drawn = 0.0, False

    def show(self, colors: Sequence[RGB]) -> None:
        now = time.time()
        if now - self._last < self.min_dt:
            return
        self._last = now
        lines = []
        for row in self.info.matrix:
            cells = []
            for i in row:
                if i is None:
                    cells.append("   ")
                else:
                    r, g, b = colors[i]
                    cells.append(f"\x1b[48;2;{r};{g};{b}m   \x1b[0m")
            lines.append(" ".join(cells))
        up = f"\x1b[{len(lines)}F" if self._drawn else ""
        self.stream.write(up + "\n".join(lines) + "\n")
        self.stream.flush()
        self._drawn = True


class ConsoleRepository(DeviceRepository):
    def __init__(self, **_):
        self.info = _virtual_info()

    def list_devices(self) -> list[DeviceInfo]:
        return [self.info]

    def open(self, selector: str | None = None) -> LightingDevice:
        return ConsoleDevice(pick([self.info], selector))


class NullDevice(LightingDevice):
    """Discards frames (status-only runs and tests)."""

    def __init__(self, info: DeviceInfo | None = None):
        self.info = info or _virtual_info()
        self.last: list[RGB] | None = None

    def show(self, colors: Sequence[RGB]) -> None:
        self.last = list(colors)
