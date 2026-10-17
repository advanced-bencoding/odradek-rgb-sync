"""Write the app icon as PNG (Linux) and ICO (Windows) for packaging. Usage: python packaging/make_icons.py OUT_DIR

The drawing lives in odradek_sync/app/icon.py (the tray uses it too); generated at build time so
the repository holds no binary files.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from odradek_sync.app.icon import ico, png  # noqa: E402

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icons")
    out.mkdir(parents=True, exist_ok=True)
    data = png(256)
    (out / "odradek-sync.png").write_bytes(data)
    (out / "odradek-sync.ico").write_bytes(ico(data))
    print(f"icons written to {out}")
