"""Loading TOML configuration: game profiles, signal maps, effect maps and device overrides.

Files are looked up by kind and name in this order, first match wins:
  1. directories passed with --config-dir
  2. the user config dir (~/.config/odradek-sync or %APPDATA%\\odradek-sync)
  3. the defaults shipped in odradek_sync/config/
So a user can override any shipped file by dropping one with the same name into their config dir.
"""
from __future__ import annotations

import tomllib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .util import user_config_dir

PACKAGE_CONFIG = Path(__file__).resolve().parent / "config"
KINDS = ("games", "signals", "effects", "devices")

# Config file format version per kind (the `format = N` key at the top of each file; missing = 1).
# Bump one only for a breaking change to that kind's structure, and list it in CHANGELOG.md.
# See RELEASING.md, "Config format versions".
FORMATS = {"games": 1, "signals": 1, "effects": 1, "devices": 1}


class ConfigError(ValueError):
    pass


class ConfigLoader:
    def __init__(self, extra_dirs: list[Path] | None = None):
        self.dirs = [Path(d) for d in (extra_dirs or [])] + [user_config_dir(), PACKAGE_CONFIG]

    def path(self, kind: str, name: str) -> Path:
        for d in self.dirs:
            p = d / kind / f"{name}.toml"
            if p.is_file():
                return p
        raise ConfigError(f"no {kind}/{name}.toml in {', '.join(map(str, self.dirs))}")

    def load(self, kind: str, name: str) -> dict:
        p = self.path(kind, name)
        try:
            data = tomllib.loads(p.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{p}: {e}") from e
        check_format(kind, data, p)
        return data

    def names(self, kind: str) -> list[str]:
        seen: dict[str, None] = {}
        for d in self.dirs:
            for p in sorted((d / kind).glob("*.toml")) if (d / kind).is_dir() else []:
                seen.setdefault(p.stem)
        return list(seen)

    # typed loaders -------------------------------------------------------

    def game(self, name: str) -> "GameProfile":
        return GameProfile.from_dict(self.load("games", name))

    def devices(self) -> list[dict]:
        return [self.load("devices", n) for n in self.names("devices")]


def check_format(kind: str, data: dict, source: Path | str) -> None:
    fmt, current = data.get("format", 1), FORMATS.get(kind, 1)
    if not isinstance(fmt, int) or fmt < 1:
        raise ConfigError(f"{source}: `format` must be a positive integer")
    if fmt > current:
        raise ConfigError(f"{source} uses {kind} format {fmt}, but this version of odradek-sync only reads "
                          f"format {current}. Update odradek-sync.")
    if fmt < current:
        raise ConfigError(f"{source} uses the old {kind} format {fmt} (current: {current}). See CHANGELOG.md "
                          "for how to update it, or delete it to use the shipped defaults.")


@dataclass(frozen=True)
class ObjectLayout:
    """Where things are inside one animation resource object (offsets from the object start)."""
    vtable_rvas: tuple[int, ...]  # vtable address minus the executable's load address, one per known build
    state_offset: int             # u32 play state: 2 idle, 3 playing, 4 held (e.g. folded)
    name_offset: int              # pointer to the resource path string


@dataclass(frozen=True)
class PauseIndicator:
    """Where one game build says it is paused, as an RVA (address minus the executable's load address).

    kind "speed": the game's speed, an f32 that is 1.0 while playing and 0 while paused.
    kind "flag": a byte that is 0 while playing and nonzero while paused.
    """
    rva: int
    kind: str = "speed"

    KINDS = {"speed": 4, "flag": 1}     # kind -> bytes to read

    @property
    def size(self) -> int:
        return self.KINDS[self.kind]

    def paused(self, raw: bytes | None) -> bool:
        if raw is None or len(raw) != self.size:
            return False                 # unreadable: carry on as if playing
        return struct.unpack("<f", raw)[0] == 0.0 if self.kind == "speed" else raw[0] != 0


@dataclass(frozen=True)
class GameProfile:
    id: str
    name: str
    executables: tuple[str, ...]
    module: str
    layout: ObjectLayout
    name_filter: str
    strip_prefix: str = "an_"
    verified_builds: tuple[str, ...] = field(default_factory=tuple)
    # build (its vtable RVA) -> where that build says it is paused
    pause: dict[int, PauseIndicator] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "GameProfile":
        try:
            g, a = d["game"], d["animation_objects"]
            rvas = a["vtable_rva"]                    # one build's RVA, or a list with one per build
            rvas = tuple(rvas) if isinstance(rvas, list) else (rvas,)
            if not rvas or not all(isinstance(r, int) for r in rvas):
                raise ConfigError("game profile: `vtable_rva` must be an integer or a list of integers")
            return cls(
                id=g["id"], name=g["name"], executables=tuple(g["executables"]),
                module=g.get("module", g["executables"][0]),
                layout=ObjectLayout(rvas, a["state_offset"], a["name_offset"]),
                name_filter=a["name_filter"], strip_prefix=a.get("strip_prefix", "an_"),
                verified_builds=tuple(g.get("verified_builds", [])),
                pause=cls._pause(d.get("pause", [])),
            )
        except KeyError as e:
            raise ConfigError(f"game profile is missing {e}") from e

    @staticmethod
    def _pause(entries: list[dict]) -> dict[int, PauseIndicator]:
        out = {}
        for e in entries:
            kind = e.get("kind", "speed")
            if kind not in PauseIndicator.KINDS:
                raise ConfigError(f"game profile: pause `kind` must be one of {', '.join(PauseIndicator.KINDS)}, "
                                  f"not {kind!r}")
            out[e["build"]] = PauseIndicator(e["rva"], kind)
        return out

    def short_name(self, path: str) -> str:
        tail = path.replace("\\", "/").rsplit("/", 1)[-1]
        return tail[len(self.strip_prefix):] if self.strip_prefix and tail.startswith(self.strip_prefix) else tail
