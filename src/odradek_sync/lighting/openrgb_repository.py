"""OpenRGB backend (Linux, Windows, macOS): talks to the OpenRGB SDK server on port 6742.

Needs the optional dependency `openrgb-python` (pip install "odradek-sync[openrgb]") and the
OpenRGB app running with its SDK server. With `autostart`, `openrgb --server` is launched if
nothing is listening.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from ..util import RGB
from .device import BackendMissingError, DeviceError, DeviceInfo, DeviceRepository, LedInfo, LightingDevice, pick


def find_openrgb() -> str | None:
    """Path of the OpenRGB executable, or None if it isn't installed."""
    for name in ("openrgb", "OpenRGB"):
        if found := shutil.which(name):
            return found
    candidates: list[Path] = []
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if base := os.environ.get(env):
                candidates += [Path(base) / "OpenRGB" / "OpenRGB.exe", Path(base) / "Programs" / "OpenRGB" / "OpenRGB.exe"]
    else:
        candidates += [Path("/usr/bin/openrgb"), Path("/usr/local/bin/openrgb"), Path.home() / "Applications" / "OpenRGB.AppImage",
                       Path("/var/lib/flatpak/exports/bin/org.openrgb.OpenRGB"),
                       Path.home() / ".local/share/flatpak/exports/bin/org.openrgb.OpenRGB"]
    return next((str(c) for c in candidates if c.is_file()), None)


class OpenRGBDevice(LightingDevice):
    def __init__(self, raw, info: DeviceInfo):
        from openrgb.utils import RGBColor
        self._raw, self.info, self._RGBColor = raw, info, RGBColor
        direct = next((m for m in raw.modes if m.name.lower() == "direct"), None)
        if direct is None:
            raise DeviceError(f"{info.name} has no Direct mode, so per-LED control isn't possible")
        raw.set_mode(direct)

    def show(self, colors: Sequence[RGB]) -> None:
        self._raw.set_colors([self._RGBColor(*c) for c in colors], fast=True)


class OpenRGBRepository(DeviceRepository):
    HELP = {
        "missing": ("OpenRGB is not installed",
                    "OpenRGB is not installed. Install it from https://openrgb.org - Odradek Sync will pick it up "
                    "automatically."),
        "no_device": ("No keyboard found (plug it in by cable)",
                      "No RGB keyboard {want}found in OpenRGB. Plug the keyboard in with its USB cable "
                      "(wireless modes usually aren't supported)."),
        "no_connection": ("Can't connect to OpenRGB", "Can't connect to OpenRGB. Retrying..."),
        "lost": ("Reconnecting to OpenRGB", "Lost the connection to OpenRGB (was it closed?). Reconnecting..."),
    }

    def __init__(self, host: str = "127.0.0.1", port: int = 6742, autostart: bool = True,
                 command: str | None = None, client_name: str = "odradek-sync"):
        self.host, self.port, self.autostart, self.command, self.client_name = host, port, autostart, command, client_name
        self._client = None

    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            from openrgb import OpenRGBClient
        except ImportError as e:
            raise DeviceError('OpenRGB support needs: pip install "odradek-sync[openrgb]"') from e
        try:
            self._client = OpenRGBClient(self.host, self.port, self.client_name)
        except (ConnectionRefusedError, OSError, TimeoutError):
            if not self.autostart:
                raise DeviceError(f"no OpenRGB SDK server on {self.host}:{self.port}; start OpenRGB with its server enabled")
            command = self.command or find_openrgb()
            if not command:
                raise BackendMissingError("OpenRGB is not installed (https://openrgb.org)")
            flags = {"creationflags": 0x08000000} if sys.platform == "win32" else {"start_new_session": True}  # no console window
            subprocess.Popen([command, "--server", "--server-port", str(self.port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
            for _ in range(30):
                time.sleep(1)
                try:
                    self._client = OpenRGBClient(self.host, self.port, self.client_name)
                    break
                except (ConnectionRefusedError, OSError, TimeoutError):
                    continue
            else:
                raise DeviceError("started OpenRGB but its server never came up")
        return self._client

    @staticmethod
    def _describe(raw, idx: int) -> DeviceInfo:
        leds = tuple(LedInfo(i, l.name.removeprefix("Key: ")) for i, l in enumerate(raw.leds))
        matrix = None
        for z in raw.zones:
            mm = getattr(z, "matrix_map", None)
            if mm:
                matrix = tuple(tuple(v for v in row) for row in mm)
                break
        return DeviceInfo(str(idx), raw.name, raw.type.name.lower(), leds, matrix)

    def reset(self) -> None:
        """Forget the connection (after OpenRGB was closed); the next call reconnects."""
        try:
            if self._client is not None:
                self._client.disconnect()
        except Exception:
            pass
        self._client = None

    def list_devices(self) -> list[DeviceInfo]:
        client = self._connect()
        return [self._describe(d, i) for i, d in enumerate(client.devices)]

    def open(self, selector: str | None = None) -> LightingDevice:
        client = self._connect()
        info = pick(self.list_devices(), selector)
        return OpenRGBDevice(client.devices[int(info.id)], info)
