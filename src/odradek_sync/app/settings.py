"""The player's settings file (settings.toml in the user config dir), created with comments on first run."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

TEMPLATE = """\
# Odradek Sync settings. Save this file, then restart Odradek Sync for changes to apply.

# Gentle effects for light sensitivity: no strobes or flicker, dimmer, smooth fades.
subtle = {subtle}

# Start Odradek Sync automatically when you log in.
autostart = {autostart}

# Which keyboard to light, by part of its name (as shown in OpenRGB). Empty = the first keyboard found.
keyboard = "{keyboard}"

# Which lighting software drives the keyboard: "auto" (z13ctl on an ASUS ROG Flow Z13, OpenRGB
# everywhere else), "openrgb" or "z13" (Linux only). The tray menu's Lighting entries change this.
lighting = "{lighting}"
"""
LIGHTING = ("auto", "openrgb", "z13")


@dataclass
class Settings:
    subtle: bool = False
    autostart: bool = True
    keyboard: str = ""
    lighting: str = "auto"

    @classmethod
    def load(cls, path: Path) -> tuple["Settings", str | None]:
        """(settings, problem). A missing file is created with defaults; a broken one falls back to defaults."""
        if not path.exists():
            s = cls()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(TEMPLATE.format(subtle="false", autostart="true", keyboard="", lighting="auto"),
                            encoding="utf-8")
            return s, None
        try:
            d = tomllib.loads(path.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as e:
            return cls(), f"settings file has a mistake ({e}); using defaults"
        lighting, problem = str(d.get("lighting", "auto")).lower(), None
        if lighting not in LIGHTING:
            lighting, problem = "auto", f'settings file: lighting = "{lighting}" isn\'t one of {", ".join(LIGHTING)}; using auto'
        return cls(bool(d.get("subtle", False)), bool(d.get("autostart", True)), str(d.get("keyboard", "")),
                   lighting), problem

    def save(self, path: Path) -> None:
        """Rewrite the file from the template (used by the tray menu's toggles)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(TEMPLATE.format(subtle=str(self.subtle).lower(), autostart=str(self.autostart).lower(),
                                        keyboard=self.keyboard.replace('"', ""), lighting=self.lighting),
                        encoding="utf-8")
