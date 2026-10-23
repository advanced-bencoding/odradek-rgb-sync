"""Windows tray via pystray (+ Pillow for the icon image). Status: written, not yet run on Windows."""
from __future__ import annotations

import io
import threading

import pystray
from PIL import Image

from ..icon import png
from . import Tray, menu_items


class WindowsTray(Tray):
    def __init__(self, on_action):
        super().__init__(on_action)
        self._images = {a: Image.open(io.BytesIO(png(64, dim=not a))) for a in (True, False)}
        self._icon: pystray.Icon | None = None
        self._lock = threading.Lock()

    def _menu(self) -> pystray.Menu:
        entries = []
        for m in menu_items(self.state):
            if m.separator:
                entries.append(pystray.Menu.SEPARATOR)
                continue
            action = (lambda a: (lambda icon, item: self.on_action(a)))(m.action) if m.action else None
            entries.append(pystray.MenuItem(m.label, action, enabled=m.enabled, radio=m.radio,
                                            checked=(lambda c: (lambda item: c))(m.checked) if m.checked is not None else None))
        return pystray.Menu(*entries)

    def start(self) -> bool:
        try:
            self._icon = pystray.Icon("odradek-sync", self._images[False], "Odradek Sync", menu=self._menu())
            threading.Thread(target=self._icon.run, name="tray", daemon=True).start()
            return True
        except Exception:
            return False

    def update(self, **changes) -> None:
        with self._lock:
            for k, v in changes.items():
                setattr(self.state, k, v)
            if self._icon is None:
                return
            self._icon.icon = self._images[self.state.active]
            self._icon.title = ("Odradek Sync\n" + "\n".join(self.state.lines))[:127]  # Windows caps tooltips at 127 chars
            self._icon.menu = self._menu()
            self._icon.update_menu()

    def stop(self) -> None:
        if self._icon is not None:
            self._icon.stop()
