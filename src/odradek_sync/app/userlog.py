"""Plain-language log for players: one short line per noteworthy event, never game-state details."""
from __future__ import annotations

import sys
import time
from pathlib import Path

MAX_BYTES = 512 * 1024


class UserLog:
    """Writes to a log file (rotated at 512 KB, one old copy kept) and to the console if there is one."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > MAX_BYTES:
            path.replace(path.with_suffix(".old.log"))
        self._f = open(path, "a", encoding="utf-8")
        self._last: str | None = None

    def info(self, message: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {message}"
        self._f.write(line + "\n")
        self._f.flush()
        out = sys.stdout  # None in a windowed (no console) Windows build
        if out is not None:
            try:
                print(line, file=out, flush=True)
            except OSError:
                pass
        self._last = message

    def once(self, message: str) -> None:
        """Log unless it's the same as the previous line (for conditions that are retried)."""
        if message != self._last:
            self.info(message)

    def close(self) -> None:
        self._f.close()
