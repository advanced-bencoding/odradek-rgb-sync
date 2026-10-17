"""Lighting devices and where they come from.

`DeviceRepository` hides the lighting backend (OpenRGB today; a vendor SDK, Windows Dynamic
Lighting or a test double tomorrow). It lists devices and opens one as a `LightingDevice`, which
only needs to describe its LEDs and accept a full frame of colours.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..util import RGB


@dataclass(frozen=True)
class LedInfo:
    index: int
    name: str                       # e.g. "Escape", "F1", "Space" (backend prefixes stripped)


@dataclass(frozen=True)
class DeviceInfo:
    id: str                         # backend-specific identifier
    name: str                       # e.g. "AULA F75"
    kind: str                       # "keyboard", "mouse", "ledstrip", ...
    leds: tuple[LedInfo, ...]
    matrix: tuple[tuple[int | None, ...], ...] | None = None  # rows x cols of LED indices, if known

    @property
    def led_count(self) -> int:
        return len(self.leds)


class LightingDevice(ABC):
    info: DeviceInfo

    @abstractmethod
    def show(self, colors: Sequence[RGB]) -> None:
        """Display one frame: exactly one colour per LED."""

    def close(self) -> None:
        pass


class DeviceRepository(ABC):
    @abstractmethod
    def list_devices(self) -> list[DeviceInfo]: ...

    @abstractmethod
    def open(self, selector: str | None = None) -> LightingDevice:
        """Open a device by (part of) its name; None = the first keyboard."""


class DeviceError(RuntimeError):
    pass


class NoDeviceError(DeviceError):
    """The backend works, but has no (matching) device: e.g. keyboard unplugged."""


class BackendMissingError(DeviceError):
    """The lighting software this backend needs isn't installed."""


def pick(devices: list[DeviceInfo], selector: str | None) -> DeviceInfo:
    if not devices:
        raise NoDeviceError("no lighting devices found")
    if selector is None:
        return next((d for d in devices if d.kind == "keyboard"), devices[0])
    sel = selector.lower()
    for d in devices:                      # an exact id wins over a name that happens to contain it
        if sel == d.id.lower():
            return d
    for d in devices:
        if sel in d.name.lower():
            return d
    raise NoDeviceError(f"no device matching {selector!r}; have: {', '.join(d.name for d in devices)}")


# name -> factory(**options). Backends register here; the CLI picks one with --lighting.
_REPOSITORIES: dict[str, Callable[..., DeviceRepository]] = {}


def register_repository(name: str, factory: Callable[..., DeviceRepository]) -> None:
    _REPOSITORIES[name] = factory


def create_repository(name: str, **options) -> DeviceRepository:
    if name not in _REPOSITORIES:
        raise DeviceError(f"unknown lighting backend {name!r}; known: {', '.join(_REPOSITORIES)}")
    return _REPOSITORIES[name](**options)


def repository_names() -> list[str]:
    return list(_REPOSITORIES)
