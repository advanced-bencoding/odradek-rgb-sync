"""Windows backend: ReadProcessMemory / VirtualQueryEx / Toolhelp snapshots via ctypes.

Status: written against the Win32 API but not yet run on Windows (development so far happened on
Linux under Proton). See CONTRIBUTING.md for how to help verify it.
"""
from __future__ import annotations

import ctypes
import sys
from collections.abc import Iterator, Sequence
from ctypes import wintypes as wt

from .base import MemoryRegion, Platform, PlatformError, ProcessInfo, ProcessMemory

if sys.platform != "win32":  # pragma: no cover - imported only on Windows
    raise ImportError("the Windows backend only works on Windows")

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
TH32CS_SNAPPROCESS = 0x00000002
TH32CS_SNAPMODULE = 0x00000008
TH32CS_SNAPMODULE32 = 0x00000010
MEM_COMMIT = 0x1000
PAGE_GUARD = 0x100
READABLE = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}  # READONLY, READWRITE, WRITECOPY, EXECUTE_*
WRITABLE = {0x04, 0x08, 0x40, 0x80}
STILL_ACTIVE = 259
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wt.DWORD),
                ("cntThreads", wt.DWORD), ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD), ("th32ProcessID", wt.DWORD),
                ("GlblcntUsage", wt.DWORD), ("ProccntUsage", wt.DWORD),
                ("modBaseAddr", ctypes.c_void_p), ("modBaseSize", wt.DWORD), ("hModule", wt.HMODULE),
                ("szModule", wt.WCHAR * 256), ("szExePath", wt.WCHAR * 260)]


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [("BaseAddress", ctypes.c_void_p), ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wt.DWORD), ("PartitionId", wt.WORD),
                ("RegionSize", ctypes.c_size_t), ("State", wt.DWORD), ("Protect", wt.DWORD),
                ("Type", wt.DWORD)]


k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.OpenProcess.restype = wt.HANDLE
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.ReadProcessMemory.restype = wt.BOOL
k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                  ctypes.POINTER(ctypes.c_size_t)]
k32.VirtualQueryEx.restype = ctypes.c_size_t
k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                               ctypes.c_size_t]
k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
k32.Process32FirstW.argtypes = k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
k32.Module32FirstW.argtypes = k32.Module32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
k32.GetExitCodeProcess.argtypes = [wt.HANDLE, ctypes.POINTER(wt.DWORD)]
k32.CloseHandle.argtypes = [wt.HANDLE]


class WindowsProcessMemory(ProcessMemory):
    def __init__(self, pid: int):
        self.pid = pid
        self._h = k32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not self._h:
            raise PlatformError(f"OpenProcess({pid}) failed (error {ctypes.get_last_error()}); "
                                "try running as the same user as the game, or as administrator")

    def read(self, address: int, size: int) -> bytes | None:
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        ok = k32.ReadProcessMemory(self._h, ctypes.c_void_p(address), buf, size, ctypes.byref(got))
        return buf.raw if ok and got.value == size else None

    def regions(self, writable_only: bool = True) -> Iterator[MemoryRegion]:
        mbi = MEMORY_BASIC_INFORMATION()
        addr = 0
        while k32.VirtualQueryEx(self._h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            prot = mbi.Protect & 0xFF
            if mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_GUARD) and prot in READABLE:
                if not writable_only or prot in WRITABLE:
                    yield MemoryRegion(base, size, prot in WRITABLE)
            addr = base + size
            if addr >= 1 << 47:
                break

    def module_range(self, module_name: str) -> tuple[int, int] | None:
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, self.pid)
        if snap == INVALID_HANDLE_VALUE:
            return None
        try:
            me = MODULEENTRY32W()
            me.dwSize = ctypes.sizeof(me)
            ok = k32.Module32FirstW(snap, ctypes.byref(me))
            while ok:
                if me.szModule.lower() == module_name.lower():
                    return me.modBaseAddr, me.modBaseAddr + me.modBaseSize
                ok = k32.Module32NextW(snap, ctypes.byref(me))
        finally:
            k32.CloseHandle(snap)
        return None

    def is_alive(self) -> bool:
        code = wt.DWORD()
        return bool(k32.GetExitCodeProcess(self._h, ctypes.byref(code))) and code.value == STILL_ACTIVE

    def close(self) -> None:
        if self._h:
            k32.CloseHandle(self._h)
            self._h = None


class WindowsPlatform(Platform):
    name = "windows"

    def find_process(self, executables: Sequence[str]) -> ProcessInfo | None:
        wanted = {e.lower() for e in executables}
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE:
            return None
        best = None
        try:
            pe = PROCESSENTRY32W()
            pe.dwSize = ctypes.sizeof(pe)
            ok = k32.Process32FirstW(snap, ctypes.byref(pe))
            while ok:
                if pe.szExeFile.lower() in wanted and (best is None or pe.cntThreads > best[1]):
                    best = (pe.th32ProcessID, pe.cntThreads, pe.szExeFile)
                ok = k32.Process32NextW(snap, ctypes.byref(pe))
        finally:
            k32.CloseHandle(snap)
        return ProcessInfo(best[0], best[2]) if best else None

    def open_process(self, pid: int) -> ProcessMemory:
        return WindowsProcessMemory(pid)
