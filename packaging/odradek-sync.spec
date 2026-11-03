# PyInstaller spec for the player app (onedir build). Run from the repo root:
#   pyinstaller --noconfirm --distpath build/dist --workpath build/work packaging/odradek-sync.spec
# Builds for the OS it runs on (PyInstaller can't cross-compile).
import re
import sys
from importlib.metadata import version as package_version
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
icons = root / "build" / "icons"


def windows_version_file() -> str | None:
    """Version resource for odradek-sync.exe (Properties > Details), from the installed package's version."""
    if sys.platform != "win32":
        return None
    from PyInstaller.utils.win32.versioninfo import (FixedFileInfo, StringFileInfo, StringStruct, StringTable,
                                                     VarFileInfo, VarStruct, VSVersionInfo)
    v = package_version("odradek-sync")                                  # e.g. 1.0.0, or 0.2.0b1
    nums = tuple(int(n) for n in re.match(r"(\d+)\.(\d+)\.(\d+)", v).groups()) + (0,)
    strings = {"ProductName": "Odradek Sync", "FileDescription": "Odradek Sync", "ProductVersion": v,
               "FileVersion": v, "CompanyName": "odradek-sync contributors", "LegalCopyright": "MIT License",
               "OriginalFilename": "odradek-sync.exe", "InternalName": "odradek-sync"}
    info = VSVersionInfo(ffi=FixedFileInfo(filevers=nums, prodvers=nums), kids=[
        StringFileInfo([StringTable("040904B0", [StringStruct(k, s) for k, s in strings.items()])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])])])
    path = root / "build" / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(info), encoding="utf-8")
    return str(path)


a = Analysis(
    [str(root / "packaging" / "entry.py")],
    pathex=[str(root / "src")],
    datas=collect_data_files("odradek_sync", includes=["config/**/*.toml"])
          + copy_metadata("odradek-sync")   # so odradek_sync.__version__ works in the frozen app
          + ([(str(icons / "odradek-sync.png"), ".")] if (icons / "odradek-sync.png").exists() else []),
    hiddenimports=[
        "odradek_sync.platform.linux" if sys.platform != "win32" else "odradek_sync.platform.windows",
        "odradek_sync.lighting.openrgb_repository",
        "openrgb",
    ] + (["odradek_sync.app.tray.win", "pystray._win32", "PIL.Image"] if sys.platform == "win32"
         else ["odradek_sync.app.tray.sni", "jeepney", "jeepney.io.blocking"]),
    excludes=["numpy", "tkinter", "odradek_sync.recon", "odradek_sync.cli"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="odradek-sync",
    console=sys.platform != "win32",   # Windows: no console window; everything goes to the log file
    icon=str(icons / "odradek-sync.ico") if sys.platform == "win32" and (icons / "odradek-sync.ico").exists() else None,
    version=windows_version_file(),
)
coll = COLLECT(exe, a.binaries, a.datas, name="odradek-sync")
