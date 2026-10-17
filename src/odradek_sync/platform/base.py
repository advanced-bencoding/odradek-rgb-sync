"""Platform abstraction: finding the game process and reading its memory (never writing).

A backend implements `Platform` (process discovery) and `ProcessMemory` (reads, region and module
enumeration). Everything above this layer works with plain addresses and bytes, so the same game
logic runs on Linux (native or Wine/Proton) and Windows.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryRegion:
    start: int
    size: int
    writable: bool

    @property
    def end(self) -> int:
        return self.start + self.size


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    executable: str


class ProcessMemory(ABC):
    """Read-only access to another process's address space."""

    pid: int

    @abstractmethod
    def read(self, address: int, size: int) -> bytes | None:
        """Exactly `size` bytes at `address`, or None if any of it is unreadable."""

    @abstractmethod
    def regions(self, writable_only: bool = True) -> Iterator[MemoryRegion]:
        """Committed, readable regions (heap and data); skips device and kernel-shared mappings."""

    @abstractmethod
    def module_range(self, module_name: str) -> tuple[int, int] | None:
        """(start, end) of a loaded module such as the game executable, matched case-insensitively."""

    @abstractmethod
    def is_alive(self) -> bool: ...

    def close(self) -> None:
        pass

    def read_u64(self, address: int) -> int | None:
        b = self.read(address, 8)
        return int.from_bytes(b, "little") if b else None

    def read_u32(self, address: int) -> int | None:
        b = self.read(address, 4)
        return int.from_bytes(b, "little") if b else None

    def read_cstring(self, address: int, limit: int = 256) -> str | None:
        b = self.read(address, limit)
        if b is None:
            return None
        return b.split(b"\0", 1)[0].decode("ascii", "replace")


class Platform(ABC):
    name: str

    @abstractmethod
    def find_process(self, executables: Sequence[str]) -> ProcessInfo | None:
        """The running game process, if any. With several matches, the main (largest) one."""

    @abstractmethod
    def open_process(self, pid: int) -> ProcessMemory: ...


class PlatformError(RuntimeError):
    pass
