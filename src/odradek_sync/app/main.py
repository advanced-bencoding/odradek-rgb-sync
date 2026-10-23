"""`odradek-sync-app`: the player-facing service. Connects to the game and drives the keyboard.

    odradek-sync-app                 run the service (what the shortcut / autostart starts)
    odradek-sync-app --stop          ask the running service to stop
    odradek-sync-app --open-log      open the log file
    odradek-sync-app --open-settings open settings.toml
    odradek-sync-app --uninstall     stop, and remove autostart and menu entries
"""
from __future__ import annotations

import argparse
import os
import queue
import signal
import subprocess
import sys
import time
import traceback
from pathlib import Path

from .. import __version__
from ..config import ConfigLoader
from ..engine import SyncEngine
from ..game import Attach, GameSession
from ..lighting import create_repository, default_effects, detect_backend
from ..lighting.compositor import EffectMap
from ..platform import PlatformError, current_platform
from ..signals import SignalMap, SignalPipeline
from ..util import user_cache_dir, user_config_dir, user_log_dir
from . import autostart
from .instance import SingleInstance
from .keyboard import ResilientKeyboard
from .settings import Settings
from .tray import Tray, create_tray
from .userlog import UserLog

GAME = "death_stranding_dc"
SETTINGS = user_config_dir() / "settings.toml"
LOG = user_log_dir() / "odradek-sync.log"


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606 - opens with the user's default app
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class StatusBoard:
    """What the tray shows: one line for the game, one for the keyboard; full-colour icon when both work."""

    def __init__(self, tray: Tray):
        self.tray = tray
        self.game, self.keyboard = ("Waiting for Death Stranding", False), ("Looking for a keyboard...", False)

    def set_game(self, text: str, ok: bool) -> None:
        self.game = (text, ok)
        self._push()

    def set_keyboard(self, text: str, ok: bool) -> None:
        self.keyboard = (text, ok)
        self._push()

    def _push(self) -> None:
        self.tray.update(lines=(self.game[0], self.keyboard[0]), active=self.game[1] and self.keyboard[1])


class StatusMessages:
    """Turns engine status changes into a few plain sentences (log) and a status line (tray)."""

    def __init__(self, log: UserLog, board: StatusBoard | None = None):
        self.log, self.connected, self.board = log, False, board

    def _show(self, text: str, ok: bool) -> None:
        if self.board:
            self.board.set_game(text, ok)

    def __call__(self, status) -> None:
        if status == Attach.NO_PROCESS:
            self._show("Waiting for Death Stranding", False)
            self.log.once("Waiting for Death Stranding to start")
        elif status == Attach.NOT_LOADED:
            self._show("Death Stranding is loading...", False)
            self.log.once("Death Stranding detected, waiting for it to finish loading")
        elif status == Attach.DENIED:
            self._show("Can't read Death Stranding's memory (see log)", False)
            if sys.platform == "win32":
                self.log.once("Can't read Death Stranding's memory. Try starting Odradek Sync as administrator.")
            else:
                self.log.once("Can't read Death Stranding's memory (permission denied). On Ubuntu and similar systems run "
                              "once: sudo sysctl kernel.yama.ptrace_scope=0 (see the README).")
        elif status == Attach.ATTACHED and not self.connected:
            self.connected = True
            self._show("Connected to Death Stranding", True)
            self.log.info("Connected to Death Stranding")
        elif status == "closed":
            self.connected = False
            self._show("Waiting for Death Stranding", False)
            self.log.info("Death Stranding closed")
        # "reloading" (objects moved after a save/area load) is handled silently


def stop_running(inst: SingleInstance) -> int:
    if not inst.is_running():
        print("Odradek Sync isn't running.")
        return 0
    inst.request_stop()
    for _ in range(40):
        time.sleep(0.25)
        if not inst.is_running():
            print("Odradek Sync stopped.")
            return 0
    print("Asked Odradek Sync to stop; it hasn't stopped yet.")
    return 1


def run_service(inst: SingleInstance) -> int:
    log = UserLog(LOG)
    if not inst.acquire():
        log.info("Odradek Sync is already running")
        return 0
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    try:
        settings, problem = Settings.load(SETTINGS)
        log.info(f"Starting service (version {__version__}{', subtle mode' if settings.subtle else ''})")
        if problem:
            log.info(problem)
        try:
            was = autostart.is_enabled()
            autostart.enable() if settings.autostart else autostart.disable()
            if settings.autostart and not was:
                log.info("Odradek Sync will start automatically when you log in (change this in the settings)")
        except Exception:
            log.info("Couldn't set up starting automatically at login")

        actions: queue.Queue = queue.Queue()
        tray = create_tray(actions.put)
        tray.state.subtle, tray.state.autostart = settings.subtle, settings.autostart
        if not tray.start():
            log.info("No system tray available; Odradek Sync runs in the background "
                     "(use \"Stop Odradek Sync\" from the menu to stop it)")
        board = StatusBoard(tray)

        loader = ConfigLoader([])
        profile = loader.game(GAME)
        smap = SignalMap.from_dict(loader.load("signals", GAME))
        backend = detect_backend()          # a ROG Flow Z13 goes through z13ctl; everything else through OpenRGB
        if backend == "z13":
            log.info("ASUS ROG Flow Z13 detected: lighting its keyboard through z13ctl")
        effect_maps = {subtle: EffectMap.from_dict(loader.load("effects", default_effects(backend, subtle)))
                       for subtle in (False, True)}
        keyboard = ResilientKeyboard(log, effect_maps[settings.subtle], loader.devices(), settings.keyboard,
                                     repo=create_repository(backend), on_status=board.set_keyboard)
        session = GameSession(current_platform(), profile, smap.animations, user_cache_dir(), log=lambda m: None)
        engine = SyncEngine(session, SignalPipeline(smap), [keyboard], fps=effect_maps[False].fps,
                            log=lambda m: None, on_status=StatusMessages(log, board))
        checked = [0.0]

        def handle(action: str) -> None:
            if action == "quit":
                stop.append(1)
            elif action == "toggle_subtle":
                settings.subtle = not settings.subtle
                settings.save(SETTINGS)
                keyboard.set_effect_map(effect_maps[settings.subtle])
                tray.update(subtle=settings.subtle)
                log.info("Subtle mode " + ("on" if settings.subtle else "off"))
            elif action == "toggle_autostart":
                settings.autostart = not settings.autostart
                settings.save(SETTINGS)
                try:
                    autostart.enable() if settings.autostart else autostart.disable()
                except Exception:
                    log.info("Couldn't change starting automatically at login")
                tray.update(autostart=settings.autostart)
                log.info("Start at login " + ("on" if settings.autostart else "off"))
            elif action == "open_log":
                open_path(LOG)
            elif action == "open_settings":
                open_path(SETTINGS)

        def should_stop() -> bool:
            while not actions.empty():   # tray clicks, handled on the main thread
                handle(actions.get())
            now = time.time()
            if now - checked[0] > 1.0:
                checked[0] = now
                if inst.stop_requested():
                    stop.append(1)
            return bool(stop)

        try:
            engine.run(should_stop)
        finally:
            tray.stop()
    except KeyboardInterrupt:
        pass
    except PlatformError as e:
        log.info(f"Odradek Sync can't run on this system: {e}")
        return 1
    except Exception as e:
        crash = LOG.with_name("odradek-sync-crash.log")
        crash.write_text(traceback.format_exc(), encoding="utf-8")
        log.info(f"Odradek Sync hit an unexpected problem and stopped ({type(e).__name__}). "
                 f"Details for a bug report: {crash}")
        return 1
    finally:
        log.info("Stopped service")
        log.close()
        inst.release()
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="odradek-sync-app", description="Mirror the Odradek on your RGB keyboard.")
    p.add_argument("--version", action="version", version=__version__)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--stop", action="store_true", help="stop the running service")
    g.add_argument("--open-log", action="store_true", help="open the log file")
    g.add_argument("--open-settings", action="store_true", help="open the settings file")
    g.add_argument("--uninstall", action="store_true", help="stop, and remove autostart and menu entries")
    args = p.parse_args(argv)
    inst = SingleInstance(user_cache_dir())
    if args.stop:
        sys.exit(stop_running(inst))
    if args.open_log:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        LOG.touch()
        open_path(LOG)
        return
    if args.open_settings:
        Settings.load(SETTINGS)
        open_path(SETTINGS)
        return
    if args.uninstall:
        if inst.is_running():
            stop_running(inst)
        autostart.remove_all()
        print("Removed autostart and menu entries. Your settings and log are kept in "
              f"{SETTINGS.parent} and {LOG.parent}.")
        return
    sys.exit(run_service(inst))
