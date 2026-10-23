"""A keyboard output that copes with real life: the lighting software (OpenRGB, or z13ctl on a ROG Flow Z13)
missing or closed, keyboard not plugged in yet.

It keeps retrying in the background and logs each situation once, in the backend's plain words (its HELP).

It can also switch to another backend while running (the tray's Lighting entries). The new backend is opened
on a worker thread while the current one keeps showing; only one that opens is swapped in. If it then fails
within SWITCH_GRACE seconds, the previous backend comes back. Either way `on_backend` hears the outcome.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from ..config import ConfigError
from ..lighting import (BACKEND_LABELS, BackendMissingError, DeviceError, FirmwareModeDevice, NoDeviceError,
                        create_repository)
from ..lighting.compositor import Compositor, EffectMap
from ..lighting.geometry import LayoutFactory
from ..outputs import Output
from ..signals import SignalPipeline
from .userlog import UserLog

RETRY_MISSING = 30.0     # lighting software not installed: check again every 30 s (the player may be installing it)
RETRY_NO_DEVICE = 10.0
RETRY_ERROR = 10.0
SWITCH_TIMEOUT = 45.0    # s to open the new backend (OpenRGB can take 30 s to start its server)
SWITCH_GRACE = 10.0      # s after a switch in which a failure means "the new backend doesn't work": go back


@dataclass
class _Switch:
    backend: str
    repo: object
    started: float
    done: threading.Event = field(default_factory=threading.Event)
    lock: threading.Lock = field(default_factory=threading.Lock)
    cancelled: bool = False
    device: object = None
    info: object = None
    geometry: object = None
    error: str = ""


def label(backend: str) -> str:
    return BACKEND_LABELS.get(backend, backend)


class ResilientKeyboard(Output):
    def __init__(self, log: UserLog, effect_map: EffectMap, device_overrides: list[dict], selector: str = "",
                 repo=None, on_status=lambda text, ok: None, backend: str = "openrgb",
                 effect_map_for: Callable[[str], EffectMap] | None = None,
                 on_backend: Callable[[str, bool], None] = lambda backend, changed: None):
        """on_status(text, ok) gets a short status for the tray, e.g. ("Keyboard: AULA F75", True).
        effect_map_for(backend) gives the effect map to run on a backend switched to.
        on_backend(backend, changed) hears every switch outcome: the backend now in use, and whether it changed."""
        self.log, self.effect_map, self.overrides = log, effect_map, device_overrides
        self.on_status, self.on_backend = on_status, on_backend
        self.effect_map_for = effect_map_for or (lambda b: self.effect_map)
        self.selector = selector or None
        self.backend = backend
        self.repo = repo or create_repository(backend)
        self.device = None
        self.compositor: Compositor | None = None
        self.next_try = 0.0
        self.status = ("", False)
        self.switching: _Switch | None = None
        self.previous: tuple[str, object, EffectMap] | None = None   # what to go back to during the grace period
        self.grace_until = 0.0

    # ---------------------------------------------------------------- connecting

    def _open(self, repo):
        """(device, info, geometry) of the keyboard to light on `repo`; raises like the repository does."""
        devices = repo.list_devices()
        keyboards = [d for d in devices if d.kind == "keyboard"]
        if self.selector:
            keyboards = [d for d in devices if self.selector.lower() in d.name.lower()]
        if not keyboards:
            raise NoDeviceError("no keyboard")
        info = keyboards[0]
        device = repo.open(info.id if not self.selector else info.name)
        return device, info, LayoutFactory().build(device.info, self.overrides)

    def _connect(self, now: float) -> None:
        try:
            self.device, info, geometry = self._open(self.repo)
            self.compositor = Compositor(self.effect_map, geometry)
            self._announce(info, geometry)
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

    def _announce(self, info, geometry) -> None:
        self.log.info(f"Keyboard detected: {info.name}")
        self._status(f"Keyboard: {info.name}", True)
        if geometry.strategy != "MatrixLayout":
            self.log.info(f"Using fallback layout for this keyboard: {geometry.description.split(';')[0]}")

    def _status(self, text: str, ok: bool) -> None:
        self.status = (text, ok)
        self.on_status(text, ok)

    def _tell(self, problem: str, once: bool = True) -> None:
        status, line = self.repo.HELP[problem]
        self._status(status, False)
        line = line.format(want=f'named "{self.selector}" ' if self.selector else "")
        if once:
            self.log.once(line)
        else:
            self.log.info(line)

    # ---------------------------------------------------------------- running

    def update(self, now, signals, states):
        if self.switching is not None:
            self._check_switch(now)
        if self.previous is not None and now >= self.grace_until:
            self.previous = None                # the switch has held: no going back any more
        if self.device is None:
            if now >= self.next_try:
                self._connect(now)
            if self.device is None:
                return
        try:
            self.device.render(self.compositor, now, signals)
        except Exception as e:
            if self.previous is not None:
                self._revert(now, str(e) or type(e).__name__)
                return
            if isinstance(e, ConfigError):
                raise                           # an effect map this device can't run: a bug, not a lost device
            self._tell("lost", once=False)
            self.device, self.compositor = None, None
            self.repo.reset()
            self.next_try = now + 2.0

    def set_effect_map(self, effect_map: EffectMap) -> None:
        """Switch effects live (e.g. subtle mode from the tray), keeping the keyboard connection."""
        self.effect_map = effect_map
        if self.compositor is not None:
            self.compositor = Compositor(effect_map, self.compositor.geometry)

    def _let_go(self) -> None:
        """Leave the current keyboard the way quitting does (idle look, or the owner's own lighting)."""
        if self.device is not None and self.compositor is not None:
            try:
                self.device.render(self.compositor, time.time(), SignalPipeline.idle())
                self.device.close()
            except Exception:
                pass
        self.device, self.compositor = None, None
        self.repo.reset()

    def close(self):
        if self.switching is not None:
            self._cancel(self.switching)
        self._let_go()

    # ---------------------------------------------------------------- switching backends

    def switch(self, backend: str, repo=None) -> bool:
        """Start switching to `backend` (False: it's the one in use, or a switch is already under way).
        The current backend keeps showing until the new one has opened; update() finishes the switch."""
        if backend == self.backend or self.switching is not None:
            return False
        sw = _Switch(backend, repo or create_repository(backend), time.time())
        self.switching = sw
        self.log.info(f"Switching lighting to {label(backend)}...")
        self.on_status(f"Switching to {label(backend)}...", False)
        threading.Thread(target=self._try, args=(sw,), name="lighting-switch", daemon=True).start()
        return True

    def _try(self, sw: _Switch) -> None:
        """Worker thread: open the new backend's keyboard, and check it can run that backend's effects."""
        try:
            device, info, geometry = self._open(sw.repo)
            if isinstance(device, FirmwareModeDevice):
                Compositor(self.effect_map_for(sw.backend), geometry).check_firmware()
            sw.device, sw.info, sw.geometry = device, info, geometry
        except BackendMissingError:
            sw.error = sw.repo.HELP["missing"][0]
        except NoDeviceError:
            sw.error = sw.repo.HELP["no_device"][0]
        except Exception as e:
            sw.error = str(e) or type(e).__name__
        with sw.lock:
            sw.done.set()
            abandoned = sw.cancelled
        if abandoned:                           # gave up waiting: don't leave it open
            self._discard(sw)

    def _check_switch(self, now: float) -> None:
        sw = self.switching
        if not sw.done.is_set():
            if now - sw.started > SWITCH_TIMEOUT and self._cancel(sw):
                self._failed(sw, f"no answer within {SWITCH_TIMEOUT:.0f} s")
            return
        self.switching = None
        if sw.error:
            self._discard(sw)
            self._failed(sw, sw.error)
            return
        previous = (self.backend, self.repo, self.effect_map)
        self._let_go()
        self.backend, self.repo, self.effect_map = sw.backend, sw.repo, self.effect_map_for(sw.backend)
        self.device, self.compositor = sw.device, Compositor(self.effect_map, sw.geometry)
        self.previous, self.grace_until = previous, now + SWITCH_GRACE
        self.log.info(f"Switched lighting to {label(sw.backend)}")
        self._announce(sw.info, sw.geometry)
        self.on_backend(sw.backend, True)

    def _cancel(self, sw: _Switch) -> bool:
        """Stop waiting for a switch. False if it finished in the meantime (then it's handled normally)."""
        with sw.lock:
            if sw.done.is_set():
                return False
            sw.cancelled = True
        self.switching = None
        return True

    @staticmethod
    def _discard(sw: _Switch) -> None:
        try:
            if sw.device is not None:
                sw.device.close()
            sw.repo.reset()
        except Exception:
            pass

    def _failed(self, sw: _Switch, reason: str) -> None:
        self.log.info(f"Couldn't switch lighting to {label(sw.backend)}: {reason}. Staying with {label(self.backend)}.")
        self.on_status(*self.status)
        self.on_backend(self.backend, False)

    def _revert(self, now: float, reason: str) -> None:
        """The backend just switched to failed straight away: go back to the previous one."""
        failed = self.backend
        backend, repo, _ = self.previous
        self.previous = None
        self._let_go()
        self.backend, self.repo, self.effect_map = backend, repo, self.effect_map_for(backend)
        self.next_try = now                     # reconnect on the next tick
        self.log.info(f"{label(failed)} stopped working right after the switch ({reason}). "
                      f"Going back to {label(backend)}.")
        self.on_backend(backend, True)
