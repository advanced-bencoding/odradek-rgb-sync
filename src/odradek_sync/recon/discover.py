"""Rediscover the animation object layout (vtable RVA, name offset, state offset) for a new game build.

1. Find resource-path strings containing a hint (default "ds/animations/") in memory.
2. Find 8-byte pointers to those strings.
3. For each pointer, look at preceding 8-byte slots for values inside the executable's image:
   each is a possible vtable, and the distance is the name offset. Objects can embed sub-objects
   with their own vtable, so several pairs show up; rank by count, then by step 4.
4. Suggest a state offset: a u32 slot between the vtable and the name that holds small integers
   (2/3/4) in almost every object.

Needs numpy (pip install "odradek-sync[recon]").
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..platform import ProcessMemory

CHUNK = 64 << 20


@dataclass
class LayoutCandidate:
    vtable_rva: int
    name_offset: int
    objects: int
    state_offsets: list[tuple[int, float]]   # (offset, share of objects with a small-int value there)
    examples: list[str]


def discover_layout(memory: ProcessMemory, module: str, hint: bytes = b"ds/animations/",
                    max_strings: int = 50000, progress=None) -> list[LayoutCandidate]:
    import numpy as np

    span = memory.module_range(module)
    if span is None:
        raise RuntimeError(f"{module} isn't loaded")
    lo, hi = span
    regions = list(memory.regions(writable_only=True))

    # 1. strings
    strings: dict[int, str] = {}
    for r in regions:
        for start in range(r.start, r.end, CHUNK):
            buf = memory.read(start, min(CHUNK, r.end - start))
            if buf is None:
                continue
            i = buf.find(hint)
            while i != -1 and len(strings) < max_strings:
                s = buf.rfind(b"\0", max(0, i - 256), i) + 1
                e = buf.find(b"\0", i)
                if e != -1 and (s > 0 or i < 256):
                    strings[start + s] = buf[s:e].decode("ascii", "replace")
                i = buf.find(hint, i + len(hint))
        if len(strings) >= max_strings:
            break
    if not strings:
        return []
    targets = np.array(sorted(strings), dtype=np.uint64)

    # 2. pointers to them
    pointers: list[tuple[int, int]] = []
    for n, r in enumerate(regions):
        for start in range(r.start, r.end, CHUNK):
            size = min(CHUNK, r.end - start) // 8 * 8
            buf = memory.read(start, size)
            if buf is None:
                continue
            arr = np.frombuffer(buf, dtype=np.uint64)
            for idx in np.flatnonzero(np.isin(arr, targets)):
                pointers.append((start + int(idx) * 8, int(arr[idx])))
        if progress:
            progress(n + 1, len(regions))

    # 3. vtable + name offset
    tally: Counter = Counter()
    objects: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for p, target in pointers:
        for off in range(8, 0x80, 8):
            vt = memory.read_u64(p - off)
            if vt is not None and lo <= vt < hi:  # objects can embed sub-objects with their own vtable,
                key = (vt - lo, off)               # so every in-image pointer is a candidate
                tally[key] += 1
                objects.setdefault(key, []).append((p - off, target))

    # 4. state offset suggestions
    out = []
    for (rva, off), count in tally.most_common(8):
        objs = objects[(rva, off)]
        shares = []
        for so in range(0x08, off, 4):
            small = sum(1 for base, _ in objs if (memory.read_u32(base + so) or 0) in (2, 3, 4))
            shares.append((so, small / len(objs)))
        shares.sort(key=lambda x: -x[1])
        out.append(LayoutCandidate(rva, off, count, shares[:3], [strings[t] for _, t in objs[:3]]))
    # most objects first; among equals prefer a layout with a clear play-state slot (the outer object)
    out.sort(key=lambda c: (-c.objects, -(c.state_offsets[0][1] if c.state_offsets else 0)))
    return out
