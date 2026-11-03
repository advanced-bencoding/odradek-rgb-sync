"""Finding the game's animation objects in memory and reading their play state.

Decima keeps every loaded animation resource as an object laid out like this (DS:DC, see RESEARCH.md):

    +0x00  vtable pointer   (same value for every object of the class; points into the exe)
    +0x08  16-byte GUID     (the object's identity)
    +0x18  u32 play state   (2 idle, 3 playing, 4 held)
    +0x28  char* path       ("ds/animations/game/odra/odra/an_odra_arm_search")

So: compute the vtable address from the exe's load address, find every 8-aligned occurrence of it
in writable memory, and read each object's name. The offsets come from the game profile.

Only the vtable moves between game builds (standard edition 1.0.8 and the Director's Cut share the
layout and the animation names), so the profile lists one vtable RVA per known build. The first scan
looks for all of them at once; whichever one finds named objects is the running build, and later
scans look for that one only.
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

from ..config import GameProfile
from ..platform import ProcessMemory

CHUNK = 64 << 20
MAX_GAP = 4096  # state fields closer than this are read in one go


@dataclass(frozen=True)
class AnimationObject:
    name: str          # short name, e.g. "odra_main_warrning_sign_lp"
    path: str          # full resource path
    address: int       # object start (the vtable pointer)

    def state_address(self, profile: GameProfile) -> int:
        return self.address + profile.layout.state_offset


class CatalogError(RuntimeError):
    pass


class AnimationCatalog:
    def __init__(self, memory: ProcessMemory, profile: GameProfile):
        self.memory, self.profile = memory, profile
        self.rva: int | None = None   # the running build's vtable RVA, once a scan has found its objects

    def vtables(self) -> dict[int, int]:
        """{vtable address: RVA} for every known build, or only the running build once it's known."""
        span = self.memory.module_range(self.profile.module)
        if span is None:
            raise CatalogError(f"{self.profile.module} isn't loaded in process {self.memory.pid}")
        rvas = self.profile.layout.vtable_rvas if self.rva is None else (self.rva,)
        return {span[0] + rva: rva for rva in rvas}

    def find_objects(self, progress: Callable[[int, int], None] | None = None) -> list[tuple[int, int]]:
        """(address, vtable RVA) of every object whose first 8 bytes are one of the animation vtables."""
        patterns = [(vt.to_bytes(8, "little"), rva) for vt, rva in self.vtables().items()]
        regions = list(self.memory.regions(writable_only=True))
        total, done, found = sum(r.size for r in regions), 0, []
        for r in regions:
            for start in range(r.start, r.end, CHUNK):
                size = min(CHUNK, r.end - start)
                buf = self.memory.read(start, size)
                done += size
                if progress:
                    progress(done, total)
                if buf is None:
                    continue
                for pattern, rva in patterns:
                    # look for the pointer's low 4 bytes, then check the rest: bytes.find skips ahead by the
                    # needle's last byte, and a pointer ends in 0x00, the most common byte (3x faster on the game)
                    i = buf.find(pattern[:4])
                    while i != -1:
                        if (start + i) % 8 == 0 and buf[i:i + 8] == pattern:
                            found.append((start + i, rva))
                        i = buf.find(pattern[:4], i + 1)
        return found

    def scan(self, name_filter: str | None = None, progress=None) -> list[AnimationObject]:
        """Every animation object whose path matches name_filter (default: the profile's)."""
        rx = re.compile(self.profile.name_filter if name_filter is None else name_filter)
        out, builds = [], set()
        for addr, rva in self.find_objects(progress):
            ptr = self.memory.read_u64(addr + self.profile.layout.name_offset)
            path = self.memory.read_cstring(ptr) if ptr and 0x10000 < ptr < 1 << 47 else None
            if path and rx.search(path):
                out.append(AnimationObject(self.profile.short_name(path), path, addr))
                builds.add(rva)
        if len(builds) == 1:
            self.rva = builds.pop()
        return out

    def still_valid(self, objects: Iterable[AnimationObject], samples: int = 20) -> bool:
        """Spot-check that the objects are still where we found them (areas and saves can reload them)."""
        objs = list(objects)
        if not objs:
            return False
        try:
            want = {vt.to_bytes(8, "little"): rva for vt, rva in self.vtables().items()}
        except CatalogError:   # exe unmapped: the game is starting up or shutting down
            return False
        step = max(1, len(objs) // samples)
        builds = {want.get(self.memory.read(o.address, 8)) for o in objs[::step]}
        if None in builds:
            return False
        if len(builds) == 1:   # objects from the cache never went through scan(): this tells the build
            self.rva = builds.pop()
        return True


class StateReader:
    """Reads the play state of a fixed set of objects with as few reads as possible."""

    def __init__(self, memory: ProcessMemory, profile: GameProfile, objects: Iterable[AnimationObject]):
        self.memory = memory
        objs = sorted(objects, key=lambda o: o.address)
        self.names = [o.name for o in objs]
        addrs = [o.state_address(profile) for o in objs]
        self.groups: list[tuple[int, int, list[int]]] = []
        start = 0
        for i in range(1, len(addrs) + 1):
            if i == len(addrs) or addrs[i] - addrs[i - 1] > MAX_GAP:
                base = addrs[start]
                self.groups.append((base, addrs[i - 1] + 4 - base, [a - base for a in addrs[start:i]]))
                start = i

    def read(self) -> dict[str, int] | None:
        """{animation name: play state}, or None if the memory can't be read (game gone?)."""
        values: list[int] = []
        for base, size, offsets in self.groups:
            b = self.memory.read(base, size)
            if b is None:
                return None
            values += [int.from_bytes(b[o:o + 4], "little") for o in offsets]
        return dict(zip(self.names, values))


class CatalogCache:
    """Remembers object addresses per process, so restarting the tool doesn't rescan 4 GB."""

    def __init__(self, path: Path):
        self.path = path

    def load(self, pid: int, profile_id: str, name_filter: str) -> list[AnimationObject] | None:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if (d.get("pid"), d.get("profile"), d.get("filter")) != (pid, profile_id, name_filter):
            return None
        return [AnimationObject(**o) for o in d["objects"]]

    def save(self, pid: int, profile_id: str, name_filter: str, objects: list[AnimationObject]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"pid": pid, "profile": profile_id, "filter": name_filter,
                                         "objects": [asdict(o) for o in objects]}), encoding="utf-8")
