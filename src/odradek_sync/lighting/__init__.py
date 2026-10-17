"""Lighting: device repositories, layout strategies, effects and the compositor."""
from .device import (BackendMissingError, DeviceError, DeviceInfo, DeviceRepository, LedInfo, LightingDevice,
                     NoDeviceError, create_repository, register_repository, repository_names)


def _openrgb(**kw):
    from .openrgb_repository import OpenRGBRepository
    return OpenRGBRepository(**kw)


def _console(**kw):
    from .console_repository import ConsoleRepository
    return ConsoleRepository(**kw)


register_repository("openrgb", _openrgb)
register_repository("console", _console)

__all__ = ["BackendMissingError", "NoDeviceError", "DeviceError", "DeviceInfo", "DeviceRepository", "LedInfo", "LightingDevice",
           "create_repository", "register_repository", "repository_names"]
