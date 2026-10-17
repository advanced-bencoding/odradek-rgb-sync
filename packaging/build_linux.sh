#!/usr/bin/env bash
# Build the Linux player app: dist/OdradekSync-<version>-x86_64.AppImage
# Needs Python 3.11+ and internet access the first time (pip packages, appimagetool).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
VERSION=$($PY -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])")

$PY -m pip install --quiet -e ".[openrgb,tray]" pyinstaller
$PY packaging/make_icons.py build/icons
$PY -m PyInstaller --noconfirm --clean --distpath build/dist --workpath build/work packaging/odradek-sync.spec

APPDIR=build/AppDir
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/share/icons/hicolor/256x256/apps"
cp -r build/dist/odradek-sync "$APPDIR/usr/bin/"
install -m 755 packaging/linux/AppRun "$APPDIR/AppRun"
cp packaging/linux/odradek-sync.desktop "$APPDIR/"
cp build/icons/odradek-sync.png "$APPDIR/odradek-sync.png"
cp build/icons/odradek-sync.png "$APPDIR/usr/share/icons/hicolor/256x256/apps/"

TOOL=build/tools/appimagetool
if [ ! -x "$TOOL" ]; then
  mkdir -p build/tools
  curl -fsSL -o "$TOOL" https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
  chmod +x "$TOOL"
fi
mkdir -p dist
ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" "dist/OdradekSync-$VERSION-x86_64.AppImage"
echo "built dist/OdradekSync-$VERSION-x86_64.AppImage"
