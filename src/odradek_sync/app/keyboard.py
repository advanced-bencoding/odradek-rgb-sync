"""A keyboard output that copes with real life: OpenRGB missing or closed, keyboard not plugged in yet.

It keeps retrying in the background and logs each situation once, in plain words.
"""
from __future__ import annotations

import time

from ..lighting import BackendMissingError, DeviceError, NoDeviceError, create_repository
from ..lighting.compositor import Compositor, EffectMap
from ..lighting.geometry import LayoutFactory
from ..outputs import Output
from ..signals import SignalPipeline
from .userlog import UserLog

RETRY_MISSING = 30.0     # OpenRGB not installed: check again every 30 s (the player may be installing it)
RETRY_NO_DEVICE = 10.0
RETRY_ERROR = 10.0


class ResilientKeyboard(Output):
    def __init__(self, log: UserLog, effect_map: EffectMap, device_overrides: list[dict], selector: str = "",
                 repo=None, on_status=lambda text, ok: None):
        """on_status(text, ok) gets a short status for the tray, e.g. ("Keyboard: AULA F75", True)."""
        self.log, self.effect_map, self.overrides, self.on_status = log, effect_map, device_overrides, on_status
        self.selector = selector or None
        self.repo = repo or create_repository("openrgb")
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
            self.on_status("OpenRGB is not installed", False)
            self.log.once("OpenRGB is not installed. Install it from https://openrgb.org - Odradek Sync will "
                          "pick it up automatically.")
            self.next_try = now + RETRY_MISSING
        except NoDeviceError:
            self.on_status("No keyboard found (plug it in by cable)", False)
            want = f'named "{self.selector}" ' if self.selector else ""
            self.log.once(f"No RGB keyboard {want}found in OpenRGB. Plug the keyboard in with its USB cable "
                          "(wireless modes usually aren't supported).")
            self.next_try = now + RETRY_NO_DEVICE
        except (DeviceError, OSError, ConnectionError, TimeoutError):
            self.on_status("Can't connect to OpenRGB", False)
            self.log.once("Can't connect to OpenRGB. Retrying...")
            self.repo.reset()
            self.next_try = now + RETRY_ERROR

    def update(self, now, signals, states):
        if self.device is None:
            if now >= self.next_try:
                self._connect(now)
            if self.device is None:
                return
        try:
            self.device.show(self.compositor.frame(now, signals))
        except Exception:
            self.log.info("Lost the connection to OpenRGB (was it closed?). Reconnecting...")
            self.on_status("Reconnecting to OpenRGB", False)
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
                self.device.show(self.compositor.frame(time.time(), SignalPipeline.idle()))
            except Exception:
                pass
        self.repo.reset()
