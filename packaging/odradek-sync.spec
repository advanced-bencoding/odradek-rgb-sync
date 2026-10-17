# PyInstaller spec for the player app (onedir build). Run from the repo root:
#   pyinstaller --noconfirm --distpath build/dist --workpath build/work packaging/odradek-sync.spec
# Builds for the OS it runs on (PyInstaller can't cross-compile).
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

root = Path(SPECPATH).parent
icons = root / "build" / "icons"

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
)
coll = COLLECT(exe, a.binaries, a.datas, name="odradek-sync")
