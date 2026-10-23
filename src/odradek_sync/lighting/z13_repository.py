"""ASUS ROG Flow Z13 (2025) backend (Linux): the keyboard and the edge lightbar, through z13ctl's daemon.

The Z13's lighting is two single-colour zones, each its own USB HID device, running ASUS Aura firmware
modes (static, breathe, strobe, cycle, rainbow). OpenRGB doesn't support them. z13ctl
(https://github.com/dahui/z13ctl) does, and its daemon owns the hardware, so we send no packets of our
own: we ask the daemon, over its Unix socket, to apply a mode to one zone. We name the zone by its
/dev/hidrawN path, which z13ctl applies without saving, so the player's own lighting stays in z13ctl's
settings, and we put it back whenever we have nothing to show and when we stop.

z13ctl also puts the player's lighting back by itself after a resume from sleep or when the detachable
keyboard is reattached. We re-send ours a few seconds after either, so the game's lighting wins.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import time
from pathlib import Path

from .device import (BackendMissingError, DeviceError, DeviceInfo, DeviceRepository, FirmwareMode, FirmwareModeDevice,
                     LedInfo, NoDeviceError, pick)

Z13_PLATFORM = sys.platform.startswith("linux")   # z13ctl is Linux-only (hidraw), and so is this backend
SYSFS = Path("/sys/class/hidraw")
# HID_ID of each zone's USB device (bus 0003 = USB, vendor 0b05 = ASUS) -> zone, product name, kind
ZONES = {
    "HID_ID=0003:00000B05:00001A30": ("keyboard", "ASUS ROG Flow Z13 keyboard", "keyboard"),
    "HID_ID=0003:00000B05:000018C6": ("lightbar", "ASUS ROG Flow Z13 lightbar", "ledstrip"),
}
AURA_REPORT = b"\x85\x5d"           # HID "Report ID 0x5d": the one interface of each device that takes Aura commands
# s after we connect or the machine wakes: land after z13ctl's own restore, which polls for a reattach every
# 2 s and, after a resume, waits for the embedded controller (3 s settle + up to 20 s of probing)
RESEND_AFTER = (3.0, 10.0, 25.0)
SLEPT = 5.0                         # wall clock running this far ahead of the monotonic clock = we were asleep
# z13ctl's defaults for a zone with nothing saved (internal/daemon/state.go defaultState)
Z13CTL_DEFAULT = {"enabled": True, "mode": "static", "color": "FF0000", "color2": "000000", "speed": "normal",
                  "brightness": 3}


def _zone_of(node: Path) -> tuple[str, str, str] | None:
    try:
        uevent = (node / "device" / "uevent").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    return next((z for hid_id, z in ZONES.items() if hid_id in uevent.upper().splitlines()), None)


def z13_present(sysfs: Path | None = None) -> bool:
    """True on an ASUS ROG Flow Z13 (2025): its keyboard or lightbar is connected."""
    return any(_zone_of(n) for n in (sysfs or SYSFS).glob("hidraw*"))


def find_zones(sysfs: Path | None = None) -> dict[str, str]:
    """zone ("keyboard", "lightbar") -> /dev/hidrawN of its Aura interface, read from sysfs alone."""
    zones = {}
    for node in sorted((sysfs or SYSFS).glob("hidraw*")):
        zone = _zone_of(node)
        if zone is None:
            continue
        try:
            if AURA_REPORT in (node / "device" / "report_descriptor").read_bytes():
                zones.setdefault(zone[0], f"/dev/{node.name}")
        except OSError:
            continue
    return zones


def z13ctl_installed() -> bool:
    """z13ctl is on the PATH, or its daemon's socket is there."""
    return shutil.which("z13ctl") is not None or os.path.exists(socket_path())


def socket_path() -> str:
    """Where z13ctl's daemon listens (z13ctl api.SocketPath)."""
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "z13ctl", "z13ctl.sock")


def to_hex(c) -> str:
    return "%02X%02X%02X" % tuple(c)


def player_lighting(state: dict, zone: str) -> dict:
    """The lighting z13ctl would restore for this zone: its per-zone override, else its all-zones setting,
    gaps filled from those and then z13ctl's defaults (z13ctl normalizeLightingState / applyLightingState)."""
    base = {**Z13CTL_DEFAULT, **{k: v for k, v in (state.get("lighting") or {}).items() if v not in ("", None)}}
    own = (state.get("devices") or {}).get(zone)
    if own is None:
        return base
    merged = {**base, **{k: v for k, v in own.items() if v not in ("", None)}}
    merged["enabled"] = bool(own.get("enabled", False))
    merged["brightness"] = own.get("brightness", 0)
    return merged


class Z13ctl:
    """z13ctl's daemon: one JSON request per connection, one JSON reply (z13ctl docs/daemon.md)."""

    def __init__(self, path: str | None = None, timeout: float = 10.0):
        self.path, self.timeout = path or socket_path(), timeout

    def request(self, req: dict) -> dict:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(self.path)
                s.settimeout(self.timeout)
                s.sendall((json.dumps(req) + "\n").encode())
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
        except (FileNotFoundError, ConnectionRefusedError) as e:
            if shutil.which("z13ctl") is None:
                raise BackendMissingError("z13ctl is not installed (https://github.com/dahui/z13ctl)") from e
            raise DeviceError(f"z13ctl's daemon isn't running (no socket at {self.path})") from e
        except OSError as e:
            raise DeviceError(f"z13ctl's daemon didn't answer: {e}") from e
        try:
            resp = json.loads(buf)
        except ValueError as e:
            raise DeviceError(f"z13ctl's daemon sent something unexpected: {buf[:80]!r}") from e
        if not resp.get("ok"):
            raise DeviceError(f"z13ctl: {resp.get('error') or 'request failed'}")
        return resp


class Z13Device(FirmwareModeDevice):
    """One Z13 zone. Sends a request only when the mode changes, plus the re-sends after connecting/waking."""

    def __init__(self, daemon: Z13ctl, info: DeviceInfo, path: str, sysfs: Path = SYSFS):
        self.daemon, self.info, self.zone, self.path = daemon, info, info.id, path
        self.node = sysfs / Path(path).name     # goes away when the keyboard is detached
        self.showing: FirmwareMode | None | str = "unknown"
        self.resend: list[float] = []
        self.clock: tuple[float, float] | None = None
        self._resend_soon(time.monotonic())

    def _resend_soon(self, mono: float) -> None:
        self.resend = [mono + s for s in RESEND_AFTER]

    def apply(self, mode: FirmwareMode | None) -> None:
        wall, mono = time.time(), time.monotonic()
        if self.clock is not None and (wall - self.clock[0]) - (mono - self.clock[1]) > SLEPT:
            self._resend_soon(mono)             # woke up: z13ctl is restoring the player's lighting
        self.clock = (wall, mono)
        if not self.node.exists():
            raise NoDeviceError(f"the Z13 {self.zone} is gone (detached?)")
        due = bool(self.resend) and mono >= self.resend[0]
        if due:
            self.resend.pop(0)
        if mode == self.showing and not due:
            return
        if mode is None:
            self._hand_back()
        elif mode.brightness == 0:
            self.daemon.request({"cmd": "off", "device": self.path})
        else:
            self.daemon.request({"cmd": "apply", "device": self.path, "mode": mode.mode, "color": to_hex(mode.color),
                                 "color2": to_hex(mode.color2), "speed": mode.speed, "brightness": mode.brightness})
        self.showing = mode

    def _hand_back(self) -> None:
        ls = player_lighting(self.daemon.request({"cmd": "get-state"}).get("state") or {}, self.zone)
        if not ls["enabled"] or not ls["brightness"]:
            self.daemon.request({"cmd": "off", "device": self.path})
        else:
            self.daemon.request({"cmd": "apply", "device": self.path, "mode": ls["mode"], "color": ls["color"],
                                 "color2": ls["color2"], "speed": ls["speed"], "brightness": ls["brightness"]})

    def close(self) -> None:
        if self.showing is not None:
            try:
                self._hand_back()
            except (DeviceError, OSError):
                pass


class Z13Repository(DeviceRepository):
    HELP = {
        "missing": ("z13ctl is not installed",
                    "This is an ASUS ROG Flow Z13: its lighting needs z13ctl (https://github.com/dahui/z13ctl). "
                    "Install it and turn on its service (systemctl --user enable --now z13ctl.socket); "
                    "Odradek Sync will pick it up automatically."),
        "no_device": ("Z13 keyboard not attached",
                      "The Z13 keyboard isn't attached. Odradek Sync will light it as soon as it is."),
        "no_connection": ("Can't reach z13ctl",
                          "Can't reach z13ctl's service. Turn it on with: systemctl --user enable --now "
                          "z13ctl.socket. Retrying..."),
        "lost": ("Reconnecting to z13ctl",
                 "Lost the Z13 keyboard (detached?) or z13ctl stopped answering. Reconnecting..."),
    }

    def __init__(self, socket_file: str | None = None, sysfs: str | Path | None = None):
        self.daemon, self.sysfs = Z13ctl(socket_file), Path(sysfs or SYSFS)

    def list_devices(self) -> list[DeviceInfo]:
        if not Z13_PLATFORM:
            raise BackendMissingError("ASUS ROG Flow Z13 lighting works on Linux only (z13ctl is Linux-only)")
        names = {z[0]: z for z in ZONES.values()}
        return [DeviceInfo(zone, names[zone][1], names[zone][2], (LedInfo(0, zone.title()),), ((0,),))
                for zone in find_zones(self.sysfs)]

    def open(self, selector: str | None = None) -> Z13Device:
        devices = self.list_devices()           # raises on anything but Linux
        if not devices:
            raise NoDeviceError("no ASUS ROG Flow Z13 keyboard or lightbar found")
        info = pick(devices, selector)
        self.daemon.request({"cmd": "get-state"})       # fail now, with a clear reason, if z13ctl isn't there
        return Z13Device(self.daemon, info, find_zones(self.sysfs)[info.id], self.sysfs)
