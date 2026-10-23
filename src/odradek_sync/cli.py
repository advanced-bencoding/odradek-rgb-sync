"""Command line: `odradek-sync run`, `effects`, `devices`, `signals`, `recon ...`."""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

from . import __version__
from .config import ConfigError, ConfigLoader
from .engine import SyncEngine
from .game import Attach, GameSession
from .lighting import DeviceError, create_repository, default_effects, detect_backend, repository_names
from .lighting.compositor import Compositor, EffectMap
from .lighting.effects import available_effects
from .lighting.geometry import LayoutFactory
from .outputs import LightingOutput, Recorder, StatusPrinter
from .platform import PlatformError, current_platform
from .signals import SignalMap, SignalPipeline
from .util import stamp, user_cache_dir


def log(msg: str) -> None:
    print(f"{stamp()}  # {msg}", file=sys.stderr, flush=True)


def _sigterm(*_):
    raise KeyboardInterrupt


# ------------------------------------------------------------------ helpers

def loader_from(args) -> ConfigLoader:
    return ConfigLoader([Path(d) for d in args.config_dir or []])


def open_lighting(args, loader: ConfigLoader, effect_map: EffectMap):
    repo = create_repository(args.lighting)
    device = repo.open(args.device)
    geometry = LayoutFactory().build(device.info, loader.devices())
    return device, Compositor(effect_map, geometry)


def attach_for_recon(args, loader: ConfigLoader) -> GameSession:
    profile = loader.game(args.game)
    name_filter = "" if getattr(args, "all", False) else (args.filter or profile.name_filter)
    session = GameSession(current_platform(), profile, set(), user_cache_dir(), name_filter, log)
    last = None
    while True:
        status = session.try_attach()
        if status == Attach.ATTACHED:
            return session
        if status != last:
            log(status.value + ("; waiting..." if status != Attach.DENIED else ""))
            last = status
        if status == Attach.DENIED:
            sys.exit(1)
        time.sleep(3)


# ------------------------------------------------------------------ commands

def cmd_run(args):
    loader = loader_from(args)
    profile = loader.game(args.game)
    smap = SignalMap.from_dict(loader.load("signals", args.signals or args.game))
    pipeline = SignalPipeline(smap)
    effect_map = EffectMap.from_dict(loader.load("effects", args.effects))
    outputs, compositor = [], None
    if args.lighting != "none":
        device, compositor = open_lighting(args, loader, effect_map)
        outputs.append(LightingOutput(device, compositor))
        log(f"lighting: {device.info.name} ({device.info.led_count} LEDs) via {args.lighting}; "
            f"layout: {compositor.geometry.description}")
    if not args.quiet and args.lighting != "console":
        outputs.append(StatusPrinter(compositor, args.show_effects))
    if args.record:
        outputs.append(Recorder(Path(args.record)))
    session = GameSession(current_platform(), profile, smap.animations, user_cache_dir(), log=log)
    engine = SyncEngine(session, pipeline, outputs, fps=args.fps or effect_map.fps, log=log)
    try:
        engine.run()
    except KeyboardInterrupt:
        pass


def cmd_devices(args):
    overrides = loader_from(args).devices()
    for d in create_repository(args.lighting).list_devices():
        g = LayoutFactory().build(d, overrides)
        extra = sorted(set(g.regions) - {"all"})
        print(f"{d.id:>3}  {d.name}  [{d.kind}, {d.led_count} LEDs]\n     layout: {g.description}"
              f"\n     regions: {', '.join(f'{r} ({len(g.regions[r])})' for r in extra)}")


def cmd_signals(args):
    smap = SignalMap.from_dict(loader_from(args).load("signals", args.signals or args.game))
    for s in smap.signals.values():
        st = "" if s.state == 3 else f" (state {s.state})"
        print(f"{s.name:18s} {s.confidence:9s} {s.description}{st}\n{'':28s} {', '.join(s.animations)}")
    for d in smap.derived:
        print(f"{d.get('active', '?'):18s} {'derived':9s} {d['kind']} of {d.get('source')} (also {d.get('level')})")
    for k, v in smap.unmapped.items():
        print(f"{k:18s} {'UNMAPPED':9s} {v}")


def cmd_effects_list(args):
    for name, doc in available_effects().items():
        print(f"{name:14s} {doc}")


def _render_for(device, compositor, seconds, signals_at):
    t0 = time.time()
    while (now := time.time()) - t0 < seconds:
        device.render(compositor, now, signals_at(now - t0))
        time.sleep(max(0.0, 1 / 30 - (time.time() - now)))


def cmd_effects_demo(args):
    loader = loader_from(args)
    effect_map = EffectMap.from_dict(loader.load("effects", args.effects))
    demos = [d for d in effect_map.demos if not args.only or any(o.lower() in d["label"].lower() for o in args.only)]
    device, _ = open_lighting(args, loader, effect_map)
    geometry = LayoutFactory().build(device.info, loader.devices())
    try:
        for d in demos:
            print(f"{stamp()}  {d['label']}", flush=True)
            comp = Compositor(effect_map, geometry)
            base, blinks = dict(d.get("signals", {})), d.get("blink", [])

            def at(t, base=base, blinks=blinks):
                s = dict(base)
                for b in blinks:
                    ph = t - b.get("offset", 0.0)
                    s[b["signal"]] = ph >= 0 and ph % b["period"] < b["width"]
                return s
            _render_for(device, comp, args.seconds, at)
    except KeyboardInterrupt:
        pass
    device.render(Compositor(effect_map, geometry), time.time(), SignalPipeline.idle())
    device.close()


def cmd_effects_show(args):
    loader = loader_from(args)
    params = json.loads(args.params) if args.params else {}
    effect_map = EffectMap.from_dict({"layer": [{"name": "show", "rule": [{"effect": args.effect, "params": params}]}]})
    device, compositor = open_lighting(args, loader, effect_map)
    try:
        _render_for(device, compositor, args.seconds or float("inf"), lambda t: {})
    except KeyboardInterrupt:
        pass
    device.close()


def cmd_recon_list(args):
    session = attach_for_recon(args, loader_from(args))
    states = session.reader.read() or {}
    for o in sorted(session.objects, key=lambda o: o.path):
        v = states.get(o.name)
        if args.active and v == 2:
            continue
        print(f"{v!s:>3}  {o.name:50s} {o.path}")
    print(f"# {len(session.objects)} objects", file=sys.stderr)


def cmd_recon_watch(args):
    from .recon import watch
    session = attach_for_recon(args, loader_from(args))
    skip = tuple(p for p in (args.ignore or ["samface_"]) if p)  # --ignore "" hides nothing
    try:
        watch(session.reader, log_path=Path(args.log) if args.log else None, ignore=lambda n: n.startswith(skip))
    except KeyboardInterrupt:
        pass


def _captures(args):
    from .recon import CaptureStore
    return CaptureStore(user_cache_dir() / f"captures-{args.game}.json")


def cmd_recon_capture(args):
    session = attach_for_recon(args, loader_from(args))
    cap = _captures(args).add(session.reader, args.label, args.seconds)
    varied = sum(1 for v in cap["states"].values() if v == -1)
    labels = {}
    for c in _captures(args).load():
        labels[c["label"]] = labels.get(c["label"], 0) + 1
    print(f"captured {args.label!r}: {len(cap['states'])} animations ({varied} changed during the capture). "
          f"Captures so far: {', '.join(f'{k}×{v}' for k, v in labels.items())}")


def cmd_recon_compare(args):
    rows = _captures(args).compare()
    if not rows:
        print("nothing yet: capture at least two different labels")
        return
    labels = sorted({l for _, per in rows for l in per})
    print(f"{'animation':50s} " + " ".join(f"{l:>10s}" for l in labels))
    for name, per in rows:
        print(f"{name:50s} " + " ".join(f"{per.get(l, '?')!s:>10s}" for l in labels))


def cmd_recon_reset(args):
    _captures(args).reset()
    print("captures cleared")


def cmd_recon_discover(args):
    from .recon import discover_layout
    profile = loader_from(args).game(args.game)
    plat = current_platform()
    info = plat.find_process(profile.executables)
    if info is None:
        sys.exit("game not running")
    mem = plat.open_process(info.pid)
    log("scanning memory twice (strings, then pointers); this takes a minute or two")
    cands = discover_layout(mem, profile.module, args.hint.encode())
    if not cands:
        print("no candidates found; try a different --hint")
        return
    for c in cands:
        so = ", ".join(f"+{o:#x} ({s:.0%})" for o, s in c.state_offsets) or "-"
        print(f"vtable_rva = {c.vtable_rva:#x}   name_offset = {c.name_offset:#x}   objects = {c.objects}\n"
              f"    state offset candidates: {so}\n    e.g. {c.examples[0] if c.examples else ''}")
    p = profile.layout
    print(f"\ncurrent profile: vtable_rva = {p.vtable_rva:#x}, name_offset = {p.name_offset:#x}, state_offset = {p.state_offset:#x}")


# ------------------------------------------------------------------ parser

LIGHTING_HELP = "lighting backend; auto = z13 on an ASUS ROG Flow Z13 (through z13ctl, Linux only), else openrgb."


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="odradek-sync", description="Mirror Death Stranding's Odradek on RGB devices.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config-dir", action="append", help="extra config directory (searched first; repeatable)")
    p.add_argument("--game", default="death_stranding_dc", help="game profile (config/games/<name>.toml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def lighting_args(sp, allow_none=False):
        sp.add_argument("--lighting", default="auto", choices=["auto"] + repository_names() + (["none"] if allow_none else []),
                        help=LIGHTING_HELP + (" none = status only." if allow_none else ""))
        sp.add_argument("--device", help="device name (substring); default: first keyboard")
        sp.add_argument("--effects", help="effect map (config/effects/<name>.toml; default: default, or z13 on a Z13)")
        sp.add_argument("--subtle", action="store_true",
                        help="accessibility mode: gentle effects, no strobes, capped brightness (= --effects subtle)")

    r = sub.add_parser("run", help="follow the game and drive the lights (Ctrl+C to stop)")
    lighting_args(r, allow_none=True)
    r.add_argument("--signals", help="signal map name (default: same as --game)")
    r.add_argument("--record", help="also write animation and signal changes to this JSONL file")
    r.add_argument("--fps", type=float, help="updates per second (default: from the effect map)")
    r.add_argument("--quiet", action="store_true", help="don't print status lines")
    r.add_argument("--show-effects", action="store_true", help="status lines include each layer's rule")
    r.set_defaults(func=cmd_run)

    d = sub.add_parser("devices", help="list lighting devices")
    d.add_argument("--lighting", default="auto", choices=["auto"] + repository_names(), help=LIGHTING_HELP)
    d.set_defaults(func=cmd_devices)

    s = sub.add_parser("signals", help="show the signal map (what each signal means and its confidence)")
    s.add_argument("--signals", help="signal map name (default: same as --game)")
    s.set_defaults(func=cmd_signals)

    e = sub.add_parser("effects", help="list, demo or show lighting effects (no game needed)")
    esub = e.add_subparsers(dest="ecmd", required=True)
    esub.add_parser("list", help="available effects").set_defaults(func=cmd_effects_list)
    ed = esub.add_parser("demo", help="play the effect map's demo scenarios")
    lighting_args(ed)
    ed.add_argument("--seconds", type=float, default=7)
    ed.add_argument("only", nargs="*", help="only scenarios whose label contains one of these words")
    ed.set_defaults(func=cmd_effects_demo)
    es = esub.add_parser("show", help="loop one effect on the whole device")
    lighting_args(es)
    es.add_argument("effect")
    es.add_argument("--params", help='JSON, e.g. \'{"color": "#ff0000", "rpm": 90}\'')
    es.add_argument("--seconds", type=float)
    es.set_defaults(func=cmd_effects_show)

    rc = sub.add_parser("recon", help="research tools for mapping new animations")
    rsub = rc.add_subparsers(dest="rcmd", required=True)

    def filter_args(sp):
        sp.add_argument("--filter", help="regex on resource paths (default: the profile's name_filter)")
        sp.add_argument("--all", action="store_true", help="every animation object (thousands)")

    rl = rsub.add_parser("list", help="list animation objects and their current state")
    filter_args(rl)
    rl.add_argument("--active", action="store_true", help="only those not in state 2")
    rl.set_defaults(func=cmd_recon_list)
    rw = rsub.add_parser("watch", help="print every animation change live; type notes as markers")
    filter_args(rw)
    rw.add_argument("--log", help="also write JSONL here")
    rw.add_argument("--ignore", action="append", help="name prefixes to hide (default: samface_)")
    rw.set_defaults(func=cmd_recon_watch)
    rcap = rsub.add_parser("capture", help="capture all states under a label (e.g. the in-game state)")
    filter_args(rcap)
    rcap.add_argument("label")
    rcap.add_argument("--seconds", type=float, default=2.0, help="sample window; changing values are ignored")
    rcap.set_defaults(func=cmd_recon_capture)
    rsub.add_parser("compare", help="animations that tell the captured labels apart").set_defaults(func=cmd_recon_compare)
    rsub.add_parser("reset", help="clear captures").set_defaults(func=cmd_recon_reset)
    rdis = rsub.add_parser("discover", help="find the object layout for a new game build (needs numpy)")
    rdis.add_argument("--hint", default="ds/animations/", help="substring of animation resource paths")
    rdis.set_defaults(func=cmd_recon_discover)
    return p


def main(argv: list[str] | None = None) -> None:
    signal.signal(signal.SIGTERM, _sigterm)
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "lighting", None) == "auto":
        args.lighting = detect_backend()
    if hasattr(args, "subtle"):
        if args.subtle and args.effects not in (None, default_effects(args.lighting, True)):
            parser.error("--subtle and --effects are mutually exclusive")
        args.effects = args.effects or default_effects(args.lighting, args.subtle)
    try:
        args.func(args)
    except (ConfigError, DeviceError, PlatformError) as e:
        sys.exit(f"error: {e}")
