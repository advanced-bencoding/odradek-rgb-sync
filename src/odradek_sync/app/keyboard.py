"""A keyboard output that copes with real life: the lighting software (OpenRGB, or z13ctl on a ROG Flow Z13)
missing or closed, keyboard not plugged in yet.

It keeps retrying in the background and logs each situation once, in the backend's plain words (its HELP).
"""
from __future__ import annotations

import time

from ..config import ConfigError
from ..lighting import BackendMissingError, DeviceError, NoDeviceError, create_repository
from ..lighting.compositor import Compositor, EffectMap
from ..lighting.geometry import LayoutFactory
from ..outputs import Output
from ..signals import SignalPipeline
from .userlog import UserLog

RETRY_MISSING = 30.0     # lighting software not installed: check again every 30 s (the player may be installing it)
RETRY_NO_DEVICE = 10.0
RETRY_ERROR = 10.0


class ResilientKeyboard(Output):
    def __init__(self, log: UserLog, effect_map: EffectMap, device_overrides: list[dict], selector: str = "",
                 repo=None, on_status=lambda text, ok: None):
        """on_status(text, ok) gets a short status for the tray, e.g. ("Keyboard: AULA F75", True)."""
        self.log, self.effect_map, self.overrides, self.on_status = log, effect_map, device_overrides, on_status
        self.selector = selector or None
        self.repo = repo or create_repository("openrgb")
        self.help = self.repo.HELP
        self.device = None
        self.compositor: Compositor | None = None
        self.next_try = 0.0

    def _connect(self, now: float) -> None:
        try:
            devices = self.repo.list_devices()
            keyboards = [d for d in devices if d.kind == "keyboard"]
            if self.selector:
                keyboards = [d for d in devices if self.selector.lower() in d.name.lower()]
            if not keyboards:
                raise NoDeviceError("no keyboard")
            info = keyboards[0]
            self.device = self.repo.open(info.id if not self.selector else info.name)
            geometry = LayoutFactory().build(self.device.info, self.overrides)
            self.compositor = Compositor(self.effect_map, geometry)
            self.log.info(f"Keyboard detected: {info.name}")
            self.on_status(f"Keyboard: {info.name}", True)
            if geometry.strategy != "MatrixLayout":
                self.log.info(f"Using fallback layout for this keyboard: {geometry.description.split(';')[0]}")
        except BackendMissingError:
            self._tell("missing")
            self.next_try = now + RETRY_MISSING
        except NoDeviceError:
            self._tell("no_device")
            self.next_try = now + RETRY_NO_DEVICE
        except (DeviceError, OSError, ConnectionError, TimeoutError):
            self._tell("no_connection")
            self.repo.reset()
            self.next_try = now + RETRY_ERROR

    def _tell(self, problem: str, once: bool = True) -> None:
        status, line = self.help[problem]
        self.on_status(status, False)
        line = line.format(want=f'named "{self.selector}" ' if self.selector else "")
        if once:
            self.log.once(line)
        else:
            self.log.info(line)

    def update(self, now, signals, states):
        if self.device is None:
            if now >= self.next_try:
                self._connect(now)
            if self.device is None:
                return
        try:
            self.device.render(self.compositor, now, signals)
        except ConfigError:
            raise                               # an effect map this device can't run: a bug, not a lost device
        except Exception:
            self._tell("lost", once=False)
            self.device, self.compositor = None, None
            self.repo.reset()
            self.next_try = now + 2.0

    def set_effect_map(self, effect_map: EffectMap) -> None:
        """Switch effects live (e.g. subtle mode from the tray), keeping the keyboard connection."""
        self.effect_map = effect_map
        if self.compositor is not None:
            self.compositor = Compositor(effect_map, self.compositor.geometry)

    def close(self):
        if self.device is not None and self.compositor is not None:
            try:
                self.device.render(self.compositor, time.time(), SignalPipeline.idle())
                self.device.close()
            except Exception:
                pass
        self.repo.reset()
