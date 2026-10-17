"""One running copy at a time, and a graceful way to ask it to stop (works the same on Linux and Windows)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


class SingleInstance:
    """Holds an OS file lock for as long as the app runs. `acquire()` is False if another copy has it."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.lock_path = directory / "odradek-sync.lock"
        self.stop_path = directory / "odradek-sync.stop"
        self._f = None

    def acquire(self) -> bool:
        f = open(self.lock_path, "a+", encoding="utf-8")
        try:
            if sys.platform == "win32":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._f = f
        f.seek(0)
        f.truncate()
        f.write(str(os.getpid()))
        f.flush()
        self.stop_path.unlink(missing_ok=True)
        return True

    def release(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None
        self.stop_path.unlink(missing_ok=True)

    # stop requests: a file the running copy polls for
    def request_stop(self) -> None:
        self.stop_path.touch()

    def stop_requested(self) -> bool:
        return self.stop_path.exists()

    def is_running(self) -> bool:
        if self._f is not None:
            return True
        probe = SingleInstance(self.lock_path.parent)
        if probe.acquire():
            probe.release()
            return False
        return True
