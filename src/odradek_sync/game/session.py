"""Attaching to the running game and keeping the animation catalog valid over time."""
from __future__ import annotations

import time
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from ..config import GameProfile
from ..platform import Platform, PlatformError, ProcessMemory
from .catalog import AnimationCatalog, AnimationObject, CatalogCache, CatalogError, StateReader

REVALIDATE_EVERY = 10.0


class Attach(Enum):
    NO_PROCESS = "game not running"
    NOT_LOADED = "game running, animations not loaded yet (menus or loading screen?)"
    DENIED = "not allowed to read the game's memory"
    ATTACHED = "attached"


class GameSession:
    """Owns the connection to one game process: find it, locate the animations, read their states.

    `required` is the set of animation names the signal map uses. If none of them are loaded yet
    the session reports NOT_LOADED and the caller retries later.
    """

    def __init__(self, platform: Platform, profile: GameProfile, required: set[str], cache_dir: Path,
                 name_filter: str | None = None, log: Callable[[str], None] = lambda m: None):
        self.platform, self.profile, self.required = platform, profile, required
        self.name_filter = profile.name_filter if name_filter is None else name_filter
        self.cache = CatalogCache(cache_dir / f"catalog-{profile.id}.json")
        self.log = log
        self.memory: ProcessMemory | None = None
        self.catalog: AnimationCatalog | None = None
        self.objects: list[AnimationObject] = []
        self.reader: StateReader | None = None
        self.pid: int | None = None
        self.pause_addr: int | None = None   # where this build says it's paused, if the profile knows
        self._closed: int | None = None      # a game process that has closed; it can linger in the process list
        self._checked = 0.0

    @property
    def attached(self) -> bool:
        return self.reader is not None

    @property
    def paused(self) -> bool:
        """The game says it is paused (the pause menu, or its window in the background).
        Always False for a build without a pause entry in the profile."""
        if self.pause_addr is None or self.memory is None:
            return False
        indicator = self.profile.pause[self.catalog.rva]
        return indicator.paused(self.memory.read(self.pause_addr, indicator.size))

    def try_attach(self) -> Attach:
        info = self.platform.find_process(self.profile.executables)
        if info is None or info.pid == self._closed:   # an exiting game stays listed, still readable, for a moment
            self._closed = self._closed if info is not None else None
            return Attach.NO_PROCESS
        if self.memory is None or self.memory.pid != info.pid:
            self.detach()
            try:
                self.memory = self.platform.open_process(info.pid)
            except PlatformError as e:
                self.log(str(e))
                return Attach.DENIED
            self.catalog = AnimationCatalog(self.memory, self.profile)
        objects = self.cache.load(info.pid, self.profile.id, self.name_filter)
        if not objects or not self.catalog.still_valid(objects):
            self.log(f"searching game memory for animation objects (pid {info.pid}, takes ~20 s)...")
            try:
                objects = self.catalog.scan(self.name_filter)
            except CatalogError:
                # the process exists but its exe isn't mapped (yet, or any more): starting or exiting
                if not self.memory.is_alive():
                    self._closed = info.pid
                    self.detach()
                    return Attach.NO_PROCESS
                return Attach.NOT_LOADED
            if objects:
                self.cache.save(info.pid, self.profile.id, self.name_filter, objects)
        names = {o.name for o in objects}
        if self.required and not (self.required & names):
            return Attach.NOT_LOADED
        missing = self.required - names
        if missing:
            self.log(f"{len(missing)} mapped animations not found in this game build: {', '.join(sorted(missing))}")
        self.objects, self.pid = objects, info.pid
        self.reader = StateReader(self.memory, self.profile, objects)
        self._checked = time.time()
        indicator = self.profile.pause.get(self.catalog.rva)
        span = self.memory.module_range(self.profile.module) if indicator is not None else None
        self.pause_addr = span[0] + indicator.rva if span else None
        build = f" (vtable RVA {self.catalog.rva:#x})" if self.catalog.rva is not None else ""
        pause = "; pause detection on" if self.pause_addr is not None else ""
        self.log(f"attached to pid {info.pid}: {len(objects)} animation objects{build}{pause}")
        return Attach.ATTACHED

    def read(self) -> dict[str, int] | None:
        """Current play states, or None if the game went away or the objects moved (re-attach)."""
        if self.reader is None:
            return None
        states = self.reader.read()
        now = time.time()
        if states is None or now - self._checked > REVALIDATE_EVERY:
            self._checked = now
            if not self.memory.is_alive():
                self.log("game closed")
                self._closed = self.pid
                self.detach()
                return None
            if not self.catalog.still_valid(self.objects):
                self.log("animation objects moved (area or save loaded); searching again")
                self.reader = None
                return None
        return states

    def detach(self) -> None:
        if self.memory is not None:
            self.memory.close()
        self.memory = self.catalog = self.reader = self.pause_addr = None
        self.objects, self.pid = [], None
