"""Linux tray: a StatusNotifierItem (the tray standard used by KDE Plasma, and by GNOME through the
AppIndicator extension, plus most other desktops) with a com.canonical.dbusmenu menu, spoken
directly over D-Bus with jeepney. No GTK or Qt needed, so it bundles cleanly into the AppImage.

One thread owns the D-Bus connection: it answers the tray host's calls and sends change signals
queued by `update()`.
"""
from __future__ import annotations

import os
import queue
import threading
from collections import deque

from jeepney import DBusAddress, HeaderFields, MatchRule, MessageType, new_error, new_method_call, new_method_return, new_signal
from jeepney.bus_messages import message_bus
from jeepney.io.blocking import open_dbus_connection

from ..icon import argb32
from . import MenuItem, Tray, menu_items

ITEM_PATH, MENU_PATH = "/StatusNotifierItem", "/MenuBar"
SNI, MENU, PROPS = "org.kde.StatusNotifierItem", "com.canonical.dbusmenu", "org.freedesktop.DBus.Properties"
WATCHER = DBusAddress("/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher", "org.kde.StatusNotifierWatcher")
SIZES = (16, 22, 32, 48, 64)

INTROSPECT = f"""<!DOCTYPE node PUBLIC "-//freedesktop//DTD D-BUS Object Introspection 1.0//EN"
"http://www.freedesktop.org/standards/dbus/1.0/introspect.dtd">
<node>
 <interface name="{SNI}">
  <property name="Category" type="s" access="read"/><property name="Id" type="s" access="read"/>
  <property name="Title" type="s" access="read"/><property name="Status" type="s" access="read"/>
  <property name="WindowId" type="i" access="read"/><property name="IconName" type="s" access="read"/>
  <property name="IconPixmap" type="a(iiay)" access="read"/><property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
  <property name="ItemIsMenu" type="b" access="read"/><property name="Menu" type="o" access="read"/>
  <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
  <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
  <signal name="NewTitle"/><signal name="NewIcon"/><signal name="NewToolTip"/>
  <signal name="NewStatus"><arg type="s"/></signal>
 </interface>
 <interface name="{MENU}">
  <property name="Version" type="u" access="read"/><property name="TextDirection" type="s" access="read"/>
  <property name="Status" type="s" access="read"/><property name="IconThemePath" type="as" access="read"/>
  <method name="GetLayout"><arg type="i" direction="in"/><arg type="i" direction="in"/><arg type="as" direction="in"/>
   <arg type="u" direction="out"/><arg type="(ia{{sv}}av)" direction="out"/></method>
  <method name="GetGroupProperties"><arg type="ai" direction="in"/><arg type="as" direction="in"/>
   <arg type="a(ia{{sv}})" direction="out"/></method>
  <method name="GetProperty"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="out"/></method>
  <method name="Event"><arg type="i" direction="in"/><arg type="s" direction="in"/><arg type="v" direction="in"/>
   <arg type="u" direction="in"/></method>
  <method name="EventGroup"><arg type="a(isvu)" direction="in"/><arg type="ai" direction="out"/></method>
  <method name="AboutToShow"><arg type="i" direction="in"/><arg type="b" direction="out"/></method>
  <method name="AboutToShowGroup"><arg type="ai" direction="in"/><arg type="ai" direction="out"/>
   <arg type="ai" direction="out"/></method>
  <signal name="LayoutUpdated"><arg type="u"/><arg type="i"/></signal>
 </interface>
</node>"""


def item_props(m: MenuItem) -> dict:
    """dbusmenu properties of one item (only non-default values)."""
    if m.separator:
        return {"type": ("s", "separator")}
    p = {"label": ("s", m.label.replace("_", "__"))}  # '_' marks mnemonics in dbusmenu
    if not m.enabled:
        p["enabled"] = ("b", False)
    if m.checked is not None:
        p["toggle-type"] = ("s", "radio" if m.radio else "checkmark")
        p["toggle-state"] = ("i", 1 if m.checked else 0)
    return p


def layout(items: list[MenuItem]) -> tuple:
    """(ia{sv}av) for the root menu: id 0 with every item as a child."""
    children = [("(ia{sv}av)", (m.id, item_props(m), [])) for m in items]
    return (0, {"children-display": ("s", "submenu")}, children)


class SniTray(Tray):
    def __init__(self, on_action):
        super().__init__(on_action)
        self._todo: queue.Queue = queue.Queue()
        self._revision = 1
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pixmaps = {True: [(s, s, argb32(s)) for s in SIZES], False: [(s, s, argb32(s, dim=True)) for s in SIZES]}

    # --- public API -------------------------------------------------------
    def start(self) -> bool:
        try:
            self.conn = open_dbus_connection(bus="SESSION")
            self.name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
            self.conn.send_and_get_reply(message_bus.RequestName(self.name, 0x4), timeout=2)
            self._calls = deque()
            self._call_filter = self.conn.filter(MatchRule(type="method_call"), queue=self._calls)
            self._signals = deque()
            rule = MatchRule(type="signal", sender="org.freedesktop.DBus", interface="org.freedesktop.DBus",
                             member="NameOwnerChanged", path="/org/freedesktop/DBus")
            rule.add_arg_condition(0, WATCHER.bus_name)
            self.conn.send_and_get_reply(message_bus.AddMatch(rule), timeout=2)
            self._signal_filter = self.conn.filter(rule, queue=self._signals)
            if not self._register():
                self.conn.close()
                return False
        except (OSError, TimeoutError, KeyError, ValueError):
            return False
        self._thread = threading.Thread(target=self._loop, name="tray", daemon=True)
        self._thread.start()
        return True

    def update(self, **changes) -> None:
        self._todo.put(changes)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        try:
            self.conn.close()
        except Exception:
            pass

    # --- D-Bus plumbing -----------------------------------------------------
    def _register(self) -> bool:
        reply = self.conn.send_and_get_reply(new_method_call(WATCHER, "RegisterStatusNotifierItem", "s", (self.name,)),
                                             timeout=2)
        return reply.header.message_type == MessageType.method_return

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._apply_updates()
            while self._signals:                      # tray host (plasmashell) restarted: register again
                sig = self._signals.popleft()
                if len(sig.body) == 3 and sig.body[2]:
                    try:
                        self._register()
                    except (OSError, TimeoutError):
                        pass
            try:
                msg = self.conn.recv_until_filtered(self._calls, timeout=0.25)
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                self._handle(msg)
            except Exception:
                self.conn.send(new_error(msg, "org.freedesktop.DBus.Error.Failed"))

    def _apply_updates(self) -> None:
        changed: set[str] = set()
        while not self._todo.empty():
            for k, v in self._todo.get().items():
                if getattr(self.state, k) != v:
                    setattr(self.state, k, v)
                    changed.add(k)
        if not changed:
            return
        item = DBusAddress(ITEM_PATH, interface=SNI)
        if "lines" in changed:
            self.conn.send(new_signal(item, "NewToolTip"))
            self.conn.send(new_signal(item, "NewTitle"))
        if "active" in changed:
            self.conn.send(new_signal(item, "NewIcon"))
        self._revision += 1
        self.conn.send(new_signal(DBusAddress(MENU_PATH, interface=MENU), "LayoutUpdated", "ui", (self._revision, 0)))

    def _item_property(self, name: str):
        s = self.state
        return {
            "Category": ("s", "ApplicationStatus"), "Id": ("s", "odradek-sync"), "Title": ("s", "Odradek Sync"),
            "Status": ("s", "Active"), "WindowId": ("i", 0), "IconName": ("s", ""),
            "IconPixmap": ("a(iiay)", self._pixmaps[s.active]), "OverlayIconName": ("s", ""),
            "OverlayIconPixmap": ("a(iiay)", []), "AttentionIconName": ("s", ""), "AttentionIconPixmap": ("a(iiay)", []),
            "AttentionMovieName": ("s", ""), "ToolTip": ("(sa(iiay)ss)", ("", [], "Odradek Sync", " · ".join(s.lines))),
            "ItemIsMenu": ("b", True), "Menu": ("o", MENU_PATH), "IconThemePath": ("s", ""),
        }.get(name)

    def _menu_property(self, name: str):
        return {"Version": ("u", 3), "TextDirection": ("s", "ltr"), "Status": ("s", "normal"),
                "IconThemePath": ("as", [])}.get(name)

    def _handle(self, msg) -> None:
        f = msg.header.fields
        path, iface, member = f.get(HeaderFields.path), f.get(HeaderFields.interface), f.get(HeaderFields.member)
        reply = lambda sig=None, body=(): self.conn.send(new_method_return(msg, sig, body))
        if iface == "org.freedesktop.DBus.Introspectable" and member == "Introspect":
            return reply("s", (INTROSPECT,))
        if iface == "org.freedesktop.DBus.Peer" and member == "Ping":
            return reply()
        if iface == PROPS:
            getter = self._item_property if path == ITEM_PATH else self._menu_property
            names = ["Category", "Id", "Title", "Status", "WindowId", "IconName", "IconPixmap", "ToolTip",
                     "ItemIsMenu", "Menu"] if path == ITEM_PATH else ["Version", "TextDirection", "Status", "IconThemePath"]
            if member == "GetAll":
                return reply("a{sv}", ({n: getter(n) for n in names},))
            if member == "Get" and getter(msg.body[1]) is not None:
                return reply("v", (getter(msg.body[1]),))
            return self.conn.send(new_error(msg, "org.freedesktop.DBus.Error.UnknownProperty"))
        if path == ITEM_PATH and iface == SNI and member in ("ContextMenu", "Activate", "SecondaryActivate", "Scroll"):
            return reply()
        if path == MENU_PATH and iface == MENU:
            items = menu_items(self.state)
            by_id = {m.id: m for m in items}
            if member == "GetLayout":
                return reply("u(ia{sv}av)", (self._revision, layout(items)))
            if member == "GetGroupProperties":
                ids = msg.body[0] or list(by_id)
                return reply("a(ia{sv})", ([(i, item_props(by_id[i])) for i in ids if i in by_id],))
            if member == "GetProperty":
                m = by_id.get(msg.body[0])
                prop = item_props(m).get(msg.body[1]) if m else None
                return reply("v", (prop or ("s", ""),))
            if member == "Event":
                self._event(by_id.get(msg.body[0]), msg.body[1])
                return reply()
            if member == "EventGroup":
                for i, event, _, _ in msg.body[0]:
                    self._event(by_id.get(i), event)
                return reply("ai", ([],))
            if member == "AboutToShow":
                return reply("b", (False,))
            if member == "AboutToShowGroup":
                return reply("aiai", ([], []))
        self.conn.send(new_error(msg, "org.freedesktop.DBus.Error.UnknownMethod"))

    def _event(self, item: MenuItem | None, event: str) -> None:
        if item and item.action and event == "clicked":
            self.on_action(item.action)
