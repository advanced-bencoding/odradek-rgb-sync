"""Lighting: device repositories, layout strategies, effects and the compositor."""
from .device import (BackendMissingError, DeviceError, DeviceInfo, DeviceRepository, FirmwareMode, FirmwareModeDevice,
                     LedInfo, LightingDevice, NoDeviceError, create_repository, register_repository, repository_names)


def _openrgb(**kw):
    from .openrgb_repository import OpenRGBRepository
    return OpenRGBRepository(**kw)


def _console(**kw):
    from .console_repository import ConsoleRepository
    return ConsoleRepository(**kw)


def _z13(**kw):
    from .z13_repository import Z13Repository
    return Z13Repository(**kw)


register_repository("openrgb", _openrgb)
register_repository("console", _console)
register_repository("z13", _z13)


def detect_backend() -> str:
    """The backend for this machine: "z13" on an ASUS ROG Flow Z13 (OpenRGB can't drive its lighting),
    otherwise "openrgb"."""
    from .z13_repository import z13_present
    return "z13" if z13_present() else "openrgb"


def default_effects(backend: str, subtle: bool = False) -> str:
    """The effect map a backend runs by default (config/effects/<name>.toml)."""
    if backend == "z13":
        return "z13_subtle" if subtle else "z13"
    return "subtle" if subtle else "default"


__all__ = ["BackendMissingError", "NoDeviceError", "DeviceError", "DeviceInfo", "DeviceRepository", "FirmwareMode",
           "FirmwareModeDevice", "LedInfo", "LightingDevice", "create_repository", "default_effects", "detect_backend",
           "register_repository", "repository_names"]
