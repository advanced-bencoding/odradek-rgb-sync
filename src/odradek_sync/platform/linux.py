"""Linux backend: /proc/<pid>/mem and /proc/<pid>/maps.

Works for native processes and for Windows games under Wine/Proton, whose PE images show up in
/proc/<pid>/maps with their file path. Reading another process needs ptrace permission: either
`kernel.yama.ptrace_scope = 0`, the same user with scope 1 and a parent/child relationship, or
CAP_SYS_PTRACE. Flatpak/pressure-vessel sandboxes don't block it.
"""
from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from pathlib import Path

from .base import MemoryRegion, Platform, PlatformError, ProcessInfo, ProcessMemory

_SKIP = ("/dev/", "[vvar", "[vsyscall", "[vdso")


def _basename(path: str) -> str:
    return re.split(r"[\\/]", path)[-1].lower()


class LinuxProcessMemory(ProcessMemory):
    def __init__(self, pid: int):
        self.pid = pid
        try:
            self._f = open(f"/proc/{pid}/mem", "rb", buffering=0)
        except PermissionError as e:
            raise PlatformError(
                f"Not allowed to read process {pid}'s memory. Check `sysctl kernel.yama.ptrace_scope` "
                "(0 allows same-user reads) or run with CAP_SYS_PTRACE."
            ) from e

    def read(self, address: int, size: int) -> bytes | None:
        try:
            self._f.seek(address)
            b = self._f.read(size)
        except (OSError, ValueError, OverflowError):
            return None
        return b if len(b) == size else None

    def _maps(self):
        try:
            lines = Path(f"/proc/{self.pid}/maps").read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            parts = line.split(None, 5)
            start, end = (int(x, 16) for x in parts[0].split("-"))
            yield start, end, parts[1], parts[5] if len(parts) > 5 else ""

    def regions(self, writable_only: bool = True) -> Iterator[MemoryRegion]:
        for start, end, perms, path in self._maps():
            if "r" not in perms or (writable_only and "w" not in perms) or path.startswith(_SKIP):
                continue
            yield MemoryRegion(start, end - start, "w" in perms)

    def module_range(self, module_name: str) -> tuple[int, int] | None:
        want = module_name.lower()
        spans = [(s, e) for s, e, _, path in self._maps() if path and _basename(path) == want]
        return (min(s for s, _ in spans), max(e for _, e in spans)) if spans else None

    def is_alive(self) -> bool:
        return Path(f"/proc/{self.pid}").exists()

    def close(self) -> None:
        self._f.close()


class LinuxPlatform(Platform):
    name = "linux"

    def find_process(self, executables: Sequence[str]) -> ProcessInfo | None:
        wanted = {e.lower() for e in executables}
        best: tuple[int, int, str] | None = None
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            try:
                args = (p / "cmdline").read_bytes().split(b"\0")
                rss = int((p / "statm").read_text(encoding="utf-8").split()[1])
            except (OSError, IndexError, ValueError):
                continue
            # Under Proton several helper processes carry the exe path; the game itself has the
            # largest resident size.
            for a in args:
                name = _basename(a.decode("utf-8", "replace"))
                if name in wanted and (best is None or rss > best[1]):
                    best = (int(p.name), rss, name)
                    break
        return ProcessInfo(best[0], best[2]) if best else None

    def open_process(self, pid: int) -> ProcessMemory:
        return LinuxProcessMemory(pid)
