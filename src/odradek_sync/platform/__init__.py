"""Pick the memory backend for the current OS. New backends register themselves here."""
from __future__ import annotations

import sys
from collections.abc import Callable

from .base import MemoryRegion, Platform, PlatformError, ProcessInfo, ProcessMemory

# sys.platform prefix -> factory. Add an entry to support another OS (e.g. "darwin").
_BACKENDS: dict[str, Callable[[], Platform]] = {}


def register_platform(prefix: str, factory: Callable[[], Platform]) -> None:
    _BACKENDS[prefix] = factory


def _linux() -> Platform:
    from .linux import LinuxPlatform
    return LinuxPlatform()


def _windows() -> Platform:
    from .windows import WindowsPlatform
    return WindowsPlatform()


register_platform("linux", _linux)
register_platform("win32", _windows)


def current_platform() -> Platform:
    for prefix, factory in _BACKENDS.items():
        if sys.platform.startswith(prefix):
            return factory()
    raise PlatformError(f"No memory backend for {sys.platform!r} yet; see CONTRIBUTING.md")


__all__ = ["MemoryRegion", "Platform", "PlatformError", "ProcessInfo", "ProcessMemory",
           "current_platform", "register_platform"]
