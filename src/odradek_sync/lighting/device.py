"""Lighting devices and where they come from.

`DeviceRepository` hides the lighting backend (OpenRGB, the ROG Flow Z13 through z13ctl; a vendor
SDK, Windows Dynamic Lighting or a test double tomorrow). It lists devices and opens one as a
`LightingDevice`, which only needs to describe its LEDs and accept a full frame of colours.

A `FirmwareModeDevice` can't take frames: it only switches between modes its firmware runs itself
(the Z13). It shows the top active layer's effect, which must name a firmware mode (`aura`).
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


@dataclass(frozen=True)
class FirmwareMode:
    """A lighting mode the device's firmware runs by itself (ASUS Aura on the ROG Flow Z13)."""
    mode: str                       # static, breathe, strobe, cycle, rainbow
    color: RGB
    color2: RGB = (0, 0, 0)         # breathe only
    speed: str = "normal"           # slow, normal, fast
    brightness: int = 3             # 0 (off) - 3


class LightingDevice(ABC):
    info: DeviceInfo

    @abstractmethod
    def show(self, colors: Sequence[RGB]) -> None:
        """Display one frame: exactly one colour per LED."""

    def render(self, compositor, now: float, signals: dict) -> None:
        """Show what the compositor has for this moment."""
        self.show(compositor.frame(now, signals))

    def close(self) -> None:
        pass


class FirmwareModeDevice(LightingDevice):
    _checked = None                 # the compositor whose effect map was last checked

    def render(self, compositor, now: float, signals: dict) -> None:
        if compositor is not self._checked:
            compositor.check_firmware()
            self._checked = compositor
        compositor.frame(now, signals)          # advances triggers and state rules
        self.apply(compositor.firmware_mode())

    def show(self, colors: Sequence[RGB]) -> None:
        raise DeviceError(f"{self.info.name} runs firmware lighting modes and can't show frames")

    @abstractmethod
    def apply(self, mode: FirmwareMode | None) -> None:
        """Switch to `mode` (nothing to do if it's already showing). None = nothing to show: hand the
        device back to the lighting its owner set up."""


class DeviceRepository(ABC):
    # Plain-language status (tray) and log lines for the player app, per problem. {want} = 'named "x" ' or ''.
    HELP = {
        "missing": ("Lighting software is not installed", "The lighting software this needs is not installed."),
        "no_device": ("No keyboard found", "No RGB keyboard {want}found."),
        "no_connection": ("Can't connect to the lighting software", "Can't connect to the lighting software. Retrying..."),
        "lost": ("Reconnecting to the keyboard", "Lost the connection to the keyboard. Reconnecting..."),
    }

    @abstractmethod
    def list_devices(self) -> list[DeviceInfo]: ...

    @abstractmethod
    def open(self, selector: str | None = None) -> LightingDevice:
        """Open a device by (part of) its name; None = the first keyboard."""

    def reset(self) -> None:
        """Forget any connection (after an error); the next call reconnects."""


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
