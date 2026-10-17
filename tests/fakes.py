"""Test doubles: an in-memory 'process' laid out like the game."""
from __future__ import annotations

from odradek_sync.config import GameProfile, ObjectLayout
from odradek_sync.platform import MemoryRegion, ProcessMemory

MODULE_BASE = 0x140000000
HEAP = 0x10000000
STRINGS = 0x20000000
VTABLE_RVA = 0x3C12968
OTHER_VTABLE_RVA = 0x3C129D0     # embedded sub-object's vtable, like the real game

PROFILE = GameProfile(
    id="test", name="Test", executables=("Game.exe",), module="Game.exe",
    layout=ObjectLayout(VTABLE_RVA, 0x18, 0x28), name_filter="/odra/",
)


class FakeMemory(ProcessMemory):
    def __init__(self):
        self.pid = 4242
        self.mem: dict[int, bytearray] = {HEAP: bytearray(0x10000), STRINGS: bytearray(0x10000)}
        self.alive = True
        self._str_top = STRINGS
        self.objects: dict[str, int] = {}

    def _locate(self, addr, size):
        for base, buf in self.mem.items():
            if base <= addr and addr + size <= base + len(buf):
                return buf, addr - base
        return None, 0

    def read(self, address, size):
        buf, off = self._locate(address, size)
        return bytes(buf[off:off + size]) if buf is not None else None

    def write(self, address, data):
        buf, off = self._locate(address, len(data))
        buf[off:off + len(data)] = data

    def regions(self, writable_only=True):
        return iter([MemoryRegion(b, len(m), True) for b, m in self.mem.items()])

    def module_range(self, module_name):
        return (MODULE_BASE, MODULE_BASE + 0x5000000) if module_name.lower() == "game.exe" else None

    def is_alive(self):
        return self.alive

    def add_object(self, path: str, state: int, slot: int) -> int:
        """Place an animation object at HEAP + slot*0xA0 (the real stride)."""
        addr = HEAP + slot * 0xA0
        s = self._str_top
        self.write(s, path.encode() + b"\0")
        self._str_top += len(path) + 1 + 7 & ~7
        self.write(addr, (MODULE_BASE + VTABLE_RVA).to_bytes(8, "little"))
        self.write(addr + 0x08, bytes(range(16)))                 # GUID
        self.write(addr + 0x18, state.to_bytes(4, "little"))
        self.write(addr + 0x20, (MODULE_BASE + OTHER_VTABLE_RVA).to_bytes(8, "little"))
        self.write(addr + 0x28, s.to_bytes(8, "little"))
        self.objects[path] = addr
        return addr

    def set_state(self, path: str, state: int) -> None:
        self.write(self.objects[path] + 0x18, state.to_bytes(4, "little"))
