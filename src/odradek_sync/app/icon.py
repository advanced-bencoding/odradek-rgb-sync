"""The app icon, drawn in code (no image files or libraries): an amber Odradek-style ring with five
"petals" and a blue core on a dark disc. Used for the tray at runtime and by packaging/make_icons.py."""
from __future__ import annotations

import math
import struct
import zlib


def rgba(n: int, dim: bool = False) -> list[list[tuple[int, int, int, int]]]:
    """n x n RGBA pixels. dim=True greys the colours out (for 'waiting' states)."""
    rows = []
    for y in range(n):
        row = []
        for x in range(n):
            dx, dy = x - n / 2 + 0.5, y - n / 2 + 0.5
            r = math.hypot(dx, dy) / (n / 2)
            if r > 1:
                row.append((0, 0, 0, 0))
                continue
            edge = max(0.02, 1.5 / n)
            a = 255 if r < 1 - edge else int(255 * (1 - r) / edge)
            if 0.62 < r < 0.80:
                k = 0.75 + 0.25 * math.cos(5 * math.atan2(dy, dx))
                c = (255 * k, 150 * k, 40 * k)
            elif r < 0.30:
                k = 1 - r / 0.3 * 0.4
                c = (20 * k, 110 * k, 255 * k)
            else:
                c = (18, 20, 26)
            if dim:
                g = (c[0] + c[1] + c[2]) / 3
                c = (g * 0.7 + 30, g * 0.7 + 30, g * 0.7 + 30) if c != (18, 20, 26) else c
            row.append((int(c[0]), int(c[1]), int(c[2]), a))
        rows.append(row)
    return rows


def argb32(n: int, dim: bool = False) -> bytes:
    """Network-byte-order ARGB, as the StatusNotifierItem IconPixmap wants."""
    return b"".join(bytes((a, r, g, b)) for row in rgba(n, dim) for r, g, b, a in row)


def png(n: int = 256, dim: bool = False) -> bytes:
    raw = b"".join(b"\0" + b"".join(bytes(p) for p in row) for row in rgba(n, dim))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", n, n, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(png_bytes: bytes) -> bytes:
    """ICO wrapping one PNG (Windows Vista+); 0 in the size fields means 256 px."""
    return struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_bytes), 22) + png_bytes
