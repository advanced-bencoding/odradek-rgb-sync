"""Start-at-login and menu entries, per OS. Kept in sync with `autostart` in settings on every launch.

Linux: XDG autostart entry (~/.config/autostart) plus "Odradek Sync" / "Stop Odradek Sync" menu
entries (~/.local/share/applications). Works on KDE, GNOME and most desktops.
Windows: HKCU\\...\\Run registry value. Start-menu shortcuts come from the installer.
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

APP_ID = "odradek-sync"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> list[str]:
    """How to start this app again: the AppImage, the frozen executable, or python -m."""
    if os.environ.get("APPIMAGE"):
        return [os.environ["APPIMAGE"]]
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "odradek_sync.app"]


def _xdg_data() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))


def _xdg_config() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _desktop_entry(name: str, args: list[str], comment: str, autostart: bool = False) -> str:
    exec_line = " ".join(shlex.quote(a) for a in launch_command() + args)
    lines = ["[Desktop Entry]", "Type=Application", f"Name={name}", f"Comment={comment}", f"Exec={exec_line}",
             "Icon=odradek-sync", "Terminal=false", "Categories=Game;Utility;"]
    if autostart:
        lines += ["X-GNOME-Autostart-enabled=true", "NoDisplay=true"]
    return "\n".join(lines) + "\n"


def _linux_files() -> dict[Path, str]:
    apps = _xdg_data() / "applications"
    return {
        _xdg_config() / "autostart" / f"{APP_ID}.desktop":
            _desktop_entry("Odradek Sync", [], "Mirror the Odradek on your keyboard", autostart=True),
        apps / f"{APP_ID}.desktop": _desktop_entry("Odradek Sync", [], "Mirror the Odradek on your keyboard"),
        apps / f"{APP_ID}-stop.desktop": _desktop_entry("Stop Odradek Sync", ["--stop"], "Stop Odradek Sync"),
        apps / f"{APP_ID}-log.desktop": _desktop_entry("Odradek Sync log", ["--open-log"], "Show the Odradek Sync log"),
    }


def enable() -> None:
    if sys.platform == "win32":
        import winreg
        cmd = " ".join(f'"{a}"' for a in launch_command())
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "OdradekSync", 0, winreg.REG_SZ, cmd)
        return
    for path, content in _linux_files().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            path.write_text(content, encoding="utf-8")
    icon = _bundled_icon()
    if icon is not None:
        dest = _xdg_data() / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png"
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(icon.read_bytes())


def _bundled_icon() -> Path | None:
    """The icon packed into the frozen build (PyInstaller puts data files under sys._MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    p = Path(base) / f"{APP_ID}.png" if base else None
    return p if p and p.is_file() else None


def disable() -> None:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "OdradekSync")
        except FileNotFoundError:
            pass
        return
    (_xdg_config() / "autostart" / f"{APP_ID}.desktop").unlink(missing_ok=True)


def remove_all() -> None:
    """Uninstall: autostart and (on Linux) the menu entries."""
    disable()
    if sys.platform != "win32":
        for path in _linux_files():
            path.unlink(missing_ok=True)
        (_xdg_data() / "icons" / "hicolor" / "256x256" / "apps" / f"{APP_ID}.png").unlink(missing_ok=True)


def is_enabled() -> bool:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, "OdradekSync")
            return True
        except FileNotFoundError:
            return False
    return (_xdg_config() / "autostart" / f"{APP_ID}.desktop").exists()
