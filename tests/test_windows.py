"""The Windows memory backend against a real process (this one). Runs on Windows only, in CI's Windows job."""
import ctypes
import os
import sys
import unittest

if sys.platform == "win32":
    from odradek_sync.platform.windows import WindowsPlatform

MEM_COMMIT_RESERVE, MEM_RELEASE = 0x3000, 0x8000
PAGE_READWRITE, PAGE_WRITECOMBINE = 0x04, 0x400


@unittest.skipUnless(sys.platform == "win32", "Windows backend")
class WindowsMemoryTest(unittest.TestCase):
    def setUp(self):
        self.mem = WindowsPlatform().open_process(os.getpid())
        self.addCleanup(self.mem.close)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.VirtualAlloc.restype = ctypes.c_void_p
        k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
        k32.VirtualFree.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32]
        self.k32 = k32

    def alloc(self, protect: int) -> int:
        addr = self.k32.VirtualAlloc(None, 0x10000, MEM_COMMIT_RESERVE, protect)
        self.assertTrue(addr, f"VirtualAlloc failed ({ctypes.get_last_error()})")
        self.addCleanup(self.k32.VirtualFree, addr, 0, MEM_RELEASE)
        return addr

    def test_reads_memory_modules_and_liveness(self):
        buf = ctypes.create_string_buffer(b"ds/animations/game/odra/odra/an_odra_arm_search")
        self.assertEqual(self.mem.read_cstring(ctypes.addressof(buf)), buf.value.decode())
        self.assertIsNone(self.mem.read(0x10, 8))
        start, end = self.mem.module_range("KERNEL32.DLL")
        self.assertLess(start, end)
        self.assertIsNone(self.mem.module_range("not-loaded.exe"))
        self.assertTrue(self.mem.is_alive())

    def test_scans_heap_but_skips_gpu_mappings(self):
        def covered(addr):
            return any(r.start <= addr < r.end for r in self.mem.regions(writable_only=True))
        self.assertTrue(covered(self.alloc(PAGE_READWRITE)))
        # write-combined pages are how GPU memory is mapped: slow to read and never hold game objects
        self.assertFalse(covered(self.alloc(PAGE_READWRITE | PAGE_WRITECOMBINE)))


if __name__ == "__main__":
    unittest.main()
