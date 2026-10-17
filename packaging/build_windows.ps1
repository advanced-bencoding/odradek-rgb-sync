# Build the Windows player app: dist\OdradekSync-<version>-setup.exe
# Needs Python 3.11+ and Inno Setup 6 (https://jrsoftware.org/isinfo.php; preinstalled on GitHub's Windows runners).
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$version = python -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"

python -m pip install --quiet -e ".[openrgb,tray]" pyinstaller
python packaging/make_icons.py build/icons
python -m PyInstaller --noconfirm --clean --distpath build/dist --workpath build/work packaging/odradek-sync.spec

$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "${env:ProgramFiles}\Inno Setup 6\ISCC.exe") |
        Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found (choco install innosetup)" }
& $iscc "/DAppVersion=$version" packaging\windows\odradek-sync.iss
Write-Host "built dist\OdradekSync-$version-setup.exe"
