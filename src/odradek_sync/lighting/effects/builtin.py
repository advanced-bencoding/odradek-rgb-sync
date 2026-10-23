"""Built-in effects. Each takes its parameters from the effect map (config/effects/*.toml)."""
from __future__ import annotations

import colorsys
import math
import random

from ...config import ConfigError
from ...util import BLACK, mix, scale, to_rgb
from ..device import FirmwareMode
from .base import Effect, FrameContext, register_effect


@register_effect("off")
class Off(Effect):
    """All LEDs off."""

    def render(self, t, ctx):
        return [BLACK] * ctx.geometry.n


@register_effect("solid")
class Solid(Effect):
    """A steady colour. params: color, brightness."""

    def setup(self):
        self.c = scale(self.color(), float(self.p("brightness", 1.0)))

    def render(self, t, ctx):
        return [self.c] * ctx.geometry.n


@register_effect("breathe")
class Breathe(Effect):
    """Slow brightness breathing. params: color, period, min, max."""

    def setup(self):
        self.c, self.period = self.color(), float(self.p("period", 5.0))
        self.lo, self.hi = float(self.p("min", 0.04)), float(self.p("max", 0.10))

    def render(self, t, ctx):
        k = self.lo + (self.hi - self.lo) * (0.5 - 0.5 * math.cos(2 * math.pi * t / self.period))
        return [scale(self.c, k)] * ctx.geometry.n


@register_effect("ring")
class Ring(Effect):
    """A ring expanding from an anchor point. params: color, origin, speed, width, floor, y_scale."""

    def setup(self):
        self.c, self.origin = self.color(), self.p("origin", "center")
        self.speed, self.width = float(self.p("speed", 9.0)), float(self.p("width", 1.8))
        self.floor, self.ys = float(self.p("floor", 0.08)), float(self.p("y_scale", 1.6))

    def render(self, t, ctx):
        o, R = ctx.geometry.point(self.origin), t * self.speed

        def led(i, p):
            d = self.dist(p, o, self.ys)
            k = max(0.0, 1 - abs(d - R) / self.width) if d <= R + self.width else 0.0
            return scale(self.c, self.floor + (1 - self.floor) * k)
        return self.each(ctx, led)


@register_effect("shockwave")
class Shockwave(Effect):
    """A bright front rolling out from an anchor with a fading trail, then fading out.
    params: color, origin, speed, width, trail, fade_after, fade_for, y_scale."""

    def setup(self):
        self.c, self.origin = self.color(), self.p("origin", "bottom_center")
        self.speed, self.width = float(self.p("speed", 15.0)), float(self.p("width", 1.5))
        self.trail, self.ys = float(self.p("trail", 0.25)), float(self.p("y_scale", 1.8))
        self.fade_after, self.fade_for = float(self.p("fade_after", 1.0)), float(self.p("fade_for", 0.6))

    def render(self, t, ctx):
        o, R = ctx.geometry.point(self.origin), t * self.speed
        fade = 1.0 if t < self.fade_after else max(0.0, 1 - (t - self.fade_after) / self.fade_for)

        def led(i, p):
            d = self.dist(p, o, self.ys)
            front = max(0.0, 1 - abs(d - R) / self.width)
            trail = max(0.0, 1 - (R - d) / 10) * self.trail if d < R else 0.0
            return scale(self.c, min(1.0, front + trail) * fade)
        return self.each(ctx, led)


@register_effect("flash_mirror")
class FlashMirror(Effect):
    """One flash each time a signal turns on, mirroring the game's own light.
    params: color, signal, flash (s), floor."""

    def setup(self):
        self.c, self.signal = self.color(), self.p("signal", "blue_flash")
        self.flash, self.floor = float(self.p("flash", 0.27)), float(self.p("floor", 0.06))

    def render(self, t, ctx):
        ago = ctx.now - ctx.rises.get(self.signal, -1e9)
        k = math.sin(math.pi * ago / self.flash) if 0 <= ago < self.flash else 0.0
        return [scale(self.c, self.floor + (1 - self.floor) * k)] * ctx.geometry.n


@register_effect("pulse")
class Pulse(Effect):
    """A flash every `period` seconds (time-driven, no signal needed). params: color, period, flash, floor."""

    def setup(self):
        self.c, self.period = self.color(), float(self.p("period", 2.0))
        self.flash, self.floor = float(self.p("flash", 0.27)), float(self.p("floor", 0.06))

    def render(self, t, ctx):
        ph = t % self.period
        k = math.sin(math.pi * ph / self.flash) if ph < self.flash else 0.0
        return [scale(self.c, self.floor + (1 - self.floor) * k)] * ctx.geometry.n


@register_effect("strobe_wave")
class StrobeWave(Effect):
    """A fast strobe rippling across the board. params: color, hz, phase_per_key, floor."""

    def setup(self):
        self.c, self.hz = self.color(), float(self.p("hz", 4.0))
        self.phase, self.floor = float(self.p("phase_per_key", 0.35)), float(self.p("floor", 0.15))

    def render(self, t, ctx):
        def led(i, p):
            k = (0.5 + 0.5 * math.sin(t * 2 * math.pi * self.hz - p[0] * self.phase)) ** 3
            return scale(self.c, self.floor + (1 - self.floor) * k)
        return self.each(ctx, led)


@register_effect("radar_sweep")
class RadarSweep(Effect):
    """A beam spinning around an anchor with a fading tail. params: color, rpm, tail (rad), floor, origin, y_scale."""

    def setup(self):
        self.c, self.rpm = self.color(), float(self.p("rpm", 60.0))
        self.tail, self.floor = float(self.p("tail", 2.2)), float(self.p("floor", 0.08))
        self.origin, self.ys = self.p("origin", "center"), float(self.p("y_scale", 1.6))

    def render(self, t, ctx):
        o, a0 = ctx.geometry.point(self.origin), t * 2 * math.pi * self.rpm / 60
        dim = scale(self.c, self.floor)

        def led(i, p):
            lag = (a0 - math.atan2((p[1] - o[1]) * self.ys, p[0] - o[0])) % (2 * math.pi)
            return mix(dim, self.c, max(0.0, 1 - lag / self.tail) ** 1.5)
        return self.each(ctx, led)


@register_effect("dying_flicker")
class DyingFlicker(Effect):
    """Dim, unsteady light with LEDs going dead one by one. params: color, max_dead (0..1), seed."""

    def setup(self):
        self.c, self.max_dead, self.seed = self.color(), float(self.p("max_dead", 0.6)), int(self.p("seed", 7))

    def render(self, t, ctx):
        rnd = self.state.setdefault("rnd", random.Random(self.seed))
        dead = self.state.setdefault("dead", set())
        n = ctx.geometry.n
        if rnd.random() < 0.06 and len(dead) < n * self.max_dead:
            dead.add(rnd.randrange(n))
        base = 0.25 + 0.15 * math.sin(t * 1.3) + (0.25 if rnd.random() < 0.03 else 0)
        return [BLACK if i in dead else scale(self.c, base * (0.6 + 0.4 * rnd.random())) for i in range(n)]


@register_effect("jitter")
class Jitter(Effect):
    """Nervous random brightness per LED. params: color, min, max, seed."""

    def setup(self):
        self.c, self.lo, self.hi = self.color(), float(self.p("min", 0.3)), float(self.p("max", 1.0))
        self.seed = int(self.p("seed", 3))

    def render(self, t, ctx):
        rnd = self.state.setdefault("rnd", random.Random(self.seed))
        return self.each(ctx, lambda i, p: scale(self.c, self.lo + (self.hi - self.lo) * rnd.random() ** 2))


@register_effect("raindrops")
class Raindrops(Effect):
    """Drops falling down random columns. params: color, background, background_brightness, rate, speed, seed."""

    def setup(self):
        self.c = self.color()
        self.bg = scale(self.color("background", "#000000"), float(self.p("background_brightness", 1.0)))
        self.rate, self.speed, self.seed = float(self.p("rate", 4.5)), float(self.p("speed", 7.0)), int(self.p("seed", 5))

    def render(self, t, ctx):
        g = ctx.geometry
        rnd = self.state.setdefault("rnd", random.Random(self.seed))
        drops = self.state.setdefault("drops", [])
        last = self.state.get("last", t)
        self.state["last"] = t
        if rnd.random() < self.rate * max(t - last, 1 / 30):
            drops.append((rnd.randrange(int(g.width)), t))
        drops[:] = [d for d in drops if (t - d[1]) * self.speed < g.height + 2]

        def led(i, p):
            k = max([max(0.0, 1 - abs(p[1] - (t - t0) * self.speed) / 1.2) for col, t0 in drops if col == int(p[0])] or [0.0])
            return mix(self.bg, self.c, k)
        return self.each(ctx, led)


@register_effect("aura")
class Aura(Effect):
    """One of the ASUS Aura firmware modes built into the ROG Flow Z13, in one colour across the device (each
    Z13 zone is single-colour). The Z13 runs it in firmware; other devices get this preview of it.
    params: mode (static, breathe, strobe, cycle, rainbow), color, color2 (breathe only),
    speed (slow, normal, fast), brightness (0-3), period (s: preview speed, overrides speed)."""

    MODES = ("static", "breathe", "strobe", "cycle", "rainbow")
    # The firmware's real periods are unknown: these are guesses until someone times a Z13.
    PERIODS = {"breathe": {"slow": 6.0, "normal": 4.0, "fast": 2.0},
               "strobe": {"slow": 1.0, "normal": 0.5, "fast": 0.25},
               "cycle": {"slow": 20.0, "normal": 10.0, "fast": 5.0}}
    # Hardware levels 0-3, scaled the way g-helper dims colours for them (Aura.cs ColorDim).
    LEVELS = (0.0, 0.1, 0.3, 1.0)

    def setup(self):
        self.mode, self.speed = self.p("mode", "static"), self.p("speed", "normal")
        if self.mode not in self.MODES:
            raise ConfigError(f"aura.mode must be one of {self.MODES}, got {self.mode!r}")
        if self.speed not in ("slow", "normal", "fast"):
            raise ConfigError(f"aura.speed must be slow, normal or fast, got {self.speed!r}")
        level = int(self.p("brightness", 3))
        if not 0 <= level <= 3:
            raise ConfigError(f"aura.brightness must be 0-3, got {level}")
        self.k = self.LEVELS[level]
        self.c, self.c2 = self.color(), self.color("color2", "#000000")
        if self.mode in ("static", "breathe", "strobe") and max(self.c) == 0:
            # The firmware reads an all-zero colour as "pick one yourself" (z13ctl PROTOCOL.md, randFlag)
            raise ConfigError("aura.color can't be black: the Z13 shows a colour of its own choosing")
        family = "breathe" if self.mode == "breathe" else "strobe" if self.mode == "strobe" else "cycle"
        self.period = float(self.p("period", self.PERIODS[family][self.speed]))
        self.firmware_mode = FirmwareMode(self.mode, to_rgb(self.c), to_rgb(self.c2), self.speed, level)

    def render(self, t, ctx):
        ph = t % self.period / self.period
        if self.mode == "breathe":
            c = mix(self.c2, self.c, 0.5 - 0.5 * math.cos(2 * math.pi * ph))
        elif self.mode == "strobe":
            c = self.c if ph < 0.5 else BLACK
        elif self.mode in ("cycle", "rainbow"):   # rainbow can only cycle on one zone
            c = tuple(255.0 * v for v in colorsys.hsv_to_rgb(ph, 1.0, 1.0))
        else:
            c = self.c
        return [scale(c, self.k)] * ctx.geometry.n


__all__ = ["FrameContext"]
