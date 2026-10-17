"""odradek-sync: read the Odradek's state from Death Stranding's memory and mirror it on RGB devices."""
from importlib.metadata import PackageNotFoundError, version

# The version lives only in pyproject.toml. Installed (and frozen) builds carry it as package
# metadata; the PyInstaller spec copies that metadata into the app.
try:
    __version__ = version("odradek-sync")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
