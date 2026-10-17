"""System tray icon: shows the app's status and offers a small menu. Optional: without a tray the app
runs exactly the same.

The tray runs on its own thread. Menu clicks are delivered as action names to `on_action`
(called on the tray thread, so keep it short, e.g. put the action on a queue):
    "toggle_subtle", "toggle_autostart", "open_log", "open_settings", "quit"
"""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass

ACTIONS = ("toggle_subtle", "toggle_autostart", "open_log", "open_settings", "quit")


@dataclass
class TrayState:
    lines: tuple[str, ...] = ("Starting...",)   # status lines, shown at the top of the menu and in the tooltip
    subtle: bool = False
    autostart: bool = True
    active: bool = False        # True when connected to the game and the keyboard (full-colour icon)


@dataclass(frozen=True)
class MenuItem:
    id: int
    label: str = ""
    action: str | None = None
    checked: bool | None = None  # None = not a checkbox
    enabled: bool = True
    separator: bool = False


def menu_items(state: TrayState) -> list[MenuItem]:
    """The menu, as data, shared by every tray backend."""
    return [MenuItem(100 + i, line, enabled=False) for i, line in enumerate(state.lines)] + [
        MenuItem(2, separator=True),
        MenuItem(3, "Subtle mode (gentle effects)", "toggle_subtle", checked=state.subtle),
        MenuItem(4, "Start at login", "toggle_autostart", checked=state.autostart),
        MenuItem(5, separator=True),
        MenuItem(6, "Open log", "open_log"),
        MenuItem(7, "Open settings file", "open_settings"),
        MenuItem(8, separator=True),
        MenuItem(9, "Quit Odradek Sync", "quit"),
    ]


class Tray(ABC):
    def __init__(self, on_action: Callable[[str], None]):
        self.on_action = on_action
        self.state = TrayState()

    @abstractmethod
    def start(self) -> bool:
        """Show the icon. False if no tray is available (the app carries on without one)."""

    @abstractmethod
    def update(self, **changes) -> None:
        """Change TrayState fields (thread-safe) and refresh the icon/menu."""

    @abstractmethod
    def stop(self) -> None: ...


class NullTray(Tray):
    def start(self) -> bool:
        return False

    def update(self, **changes) -> None:
        for k, v in changes.items():
            setattr(self.state, k, v)

    def stop(self) -> None:
        pass


def create_tray(on_action: Callable[[str], None]) -> Tray:
    try:
        if sys.platform == "win32":
            from .win import WindowsTray
            return WindowsTray(on_action)
        if sys.platform.startswith("linux"):
            from .sni import SniTray
            return SniTray(on_action)
    except ImportError:
        pass
    return NullTray(on_action)
