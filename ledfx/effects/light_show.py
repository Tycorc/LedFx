"""Light Show: pattern based party effects for a room of smart bulbs."""

import timeit

import numpy as np
import voluptuous as vol

from ledfx.color import parse_color, validate_color
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.utils.step_trigger import StepTrigger, step_trigger_schema


class LightShowEffect(AudioReactiveEffect, GradientEffect):
    """
    Party patterns in the style of the entertainment effect libraries of
    Hue DJ apps (strobe cycles, scatter fades, stage strobes, fills, waves,
    palette loops, backlit variants...).

    Those libraries are dozens of named effects, but every one of them is a
    combination of four things, which is what this effect exposes:

    - pattern:  which lamps light up on every step
    - envelope: what a lit lamp does during the step (strobe, hold, fade...)
    - colours:  where the lamp colours come from
    - backlight: what the lamps that are not lit show

    Steps are driven by the beat tracker, bass hits, onsets or a timer, see
    StepTrigger. The output is treated as a handful of independent lamps
    (one per pixel on a Hue zone, blocks on a strip) just like Rave.
    """

    NAME = "Light Show"
    CATEGORY = "BPM"
    HIDDEN_KEYS = ["gradient_roll"]
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "zones",
        "color_step",
        "strobe_flashes",
        "flare_color",
    ]

    PATTERNS = [
        "all",
        "cycle",
        "scatter",
        "double",
        "double scatter",
        "stage",
        "fill",
        "scatter fill",
        "split",
        "wave",
        "loop",
    ]
    ENVELOPES = ["strobe", "hold", "fade", "grow", "glow", "flare"]
    COLOR_MODES = ["cycle", "random", "per lamp"]

    # Minimum distance along the palette between a lamp's old and new
    # colour in random colour mode, so that every step is a visible change
    MIN_PALETTE_STEP = 0.15
    # With at most this many pixels every pixel is treated as its own lamp
    AUTO_ZONE_PIXEL_LIMIT = 32
    # Zone count used for larger outputs (strips, matrices) when zones is 0
    AUTO_ZONE_COUNT = 8
    # Longest a single strobe flash stays on, in seconds
    STROBE_ON_TIME = 0.05
    # Part of the step over which a flare blends from the flare colour to
    # the lamp colour
    FLARE_BLEND = 0.25

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "pattern",
                description="Which lamps light up on each step",
                default="cycle",
            ): vol.In(PATTERNS),
            vol.Optional(
                "envelope",
                description="What a lit lamp does during the step",
                default="fade",
            ): vol.In(ENVELOPES),
            vol.Optional(
                "color_mode",
                description="Where lamp colours come from: step along the palette, random palette colours, or a fixed palette colour per lamp",
                default="cycle",
            ): vol.In(COLOR_MODES),
            **step_trigger_schema(),
            vol.Optional(
                "stages",
                description="Groups for the stage pattern, peaks for wave, palette repeats for loop",
                default=3,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
            vol.Optional(
                "backlight",
                description="Colour shown by the lamps that are not lit",
                default="#000000",
            ): validate_color,
            vol.Optional(
                "backlight_brightness",
                description="Brightness of the backlight, 0 turns unlit lamps off",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "zones",
                description="Number of lamps / zones to split the output into. 0 = auto (one per pixel for bulbs)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=64)),
            vol.Optional(
                "color_step",
                description="How far along the palette the colour moves per step in cycle colour mode. 0 keeps one colour",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "strobe_flashes",
                description="Flashes per step for the strobe envelope",
                default=1,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
            vol.Optional(
                "flare_color",
                description="Colour a flare starts from before settling on the lamp colour",
                default="#FFFFFF",
            ): validate_color,
        }
    )

    def on_activate(self, pixel_count):
        now = timeit.default_timer()
        self._rng = np.random.default_rng()
        self._stepper = StepTrigger(self._config, now)
        self._step_count = 0
        self._cursor = -1
        self._stage = -1
        self._split_side = 1
        self._fill_order = None
        self._filled = 0
        self._color_point = self._rng.random()
        self._zone_points = None
        self._zone_colors = None
        self._build_zones(pixel_count)
        self._lit_now = np.zeros(self._zone_count, dtype=bool)
        self._lit = np.zeros(self._zone_count, dtype=bool)
        self._step(now)

    def config_updated(self, config):
        self.pattern = self._config["pattern"]
        self.envelope = self._config["envelope"]
        self.color_mode = self._config["color_mode"]
        self.stages = self._config["stages"]
        self.color_step = self._config["color_step"]
        self.strobe_flashes = self._config["strobe_flashes"]
        self.backlight = (
            np.array(parse_color(self._config["backlight"]), dtype=float)
            * self._config["backlight_brightness"]
        )
        self.flare_color = np.array(
            parse_color(self._config["flare_color"]), dtype=float
        )
        if getattr(self, "_stepper", None) is not None:
            self._stepper.configure(self._config)
        if getattr(self, "pixels", None) is not None:
            self._build_zones(self.pixel_count)
            if len(self._lit_now) != self._zone_count:
                # The lamp count changed, start the pattern over
                self._lit_now = np.zeros(self._zone_count, dtype=bool)
                self._lit = np.zeros(self._zone_count, dtype=bool)
                self._fill_order = None
                self._filled = 0
            self._recolor_per_lamp()

    # ---------------------------------------------------------------- zones

    def _build_zones(self, pixel_count):
        """Map pixels onto lamps, keeping the colours of lamps that survive."""
        zones = self._config["zones"]
        if zones <= 0:
            if pixel_count <= self.AUTO_ZONE_PIXEL_LIMIT:
                zones = pixel_count
            else:
                zones = self.AUTO_ZONE_COUNT
        zones = max(1, min(zones, pixel_count))

        self._zone_count = zones
        self._zone_of_pixel = (np.arange(pixel_count) * zones) // pixel_count

        points = np.zeros(zones)
        colors = np.zeros((zones, 3))
        old_points = self._zone_points
        kept = 0
        if old_points is not None:
            kept = min(len(old_points), zones)
            points[:kept] = old_points[:kept]
            colors[:kept] = self._zone_colors[:kept]
        if zones > kept:
            points[kept:] = self._rng.random(zones - kept)
            colors[kept:] = self._palette(points[kept:])

        self._zone_points = points
        self._zone_colors = colors
        self._cursor %= zones
        self._stage %= max(1, self.stages)
        self._recolor_per_lamp()

    def _palette(self, points):
        """Look up palette colours, shape (N, 3), for points in [0, 1]."""
        return self.get_gradient_color_vectorized1d(
            np.asarray(points, dtype=float) % 1.0
        )

    def _lamp_positions(self):
        """Position of every lamp along the output, the centre of its slot."""
        return (np.arange(self._zone_count) + 0.5) / self._zone_count

    def _recolor_per_lamp(self):
        if self.color_mode == "per lamp" and self._zone_points is not None:
            self._zone_points = self._lamp_positions()
            self._zone_colors = self._palette(self._zone_points)

    def _next_points(self, points):
        """Move each point along the palette by a random, clearly visible amount."""
        shift = self._rng.uniform(
            self.MIN_PALETTE_STEP,
            1.0 - self.MIN_PALETTE_STEP,
            size=len(points),
        )
        return (points + shift) % 1.0

    # ---------------------------------------------------------------- steps

    def _pick_lamps(self):
        """Return the boolean mask of lamps lit by this step."""
        n = self._zone_count
        pattern = self.pattern
        active = np.zeros(n, dtype=bool)

        if pattern in ("all", "wave", "loop"):
            active[:] = True

        elif pattern == "cycle":
            self._cursor = (self._cursor + 1) % n
            active[self._cursor] = True

        elif pattern == "scatter":
            self._cursor = self._random_lamp(exclude=self._cursor)
            active[self._cursor] = True

        elif pattern == "double":
            self._cursor = (self._cursor + 1) % n
            active[self._cursor] = True
            active[(self._cursor + n // 2) % n] = True

        elif pattern == "double scatter":
            first = self._random_lamp(exclude=self._cursor)
            active[first] = True
            active[self._random_lamp(exclude=first)] = True
            self._cursor = first

        elif pattern == "stage":
            stages = min(self.stages, n)
            self._stage = (self._stage + 1) % stages
            active[np.arange(n) % stages == self._stage] = True

        elif pattern in ("fill", "scatter fill"):
            if self._fill_order is None or self._filled >= n:
                # A full room clears and the fill starts over on this step
                self._lit[:] = False
                self._filled = 0
                if pattern == "scatter fill":
                    self._fill_order = self._rng.permutation(n)
                else:
                    self._fill_order = np.arange(n)
            lamp = self._fill_order[self._filled]
            self._filled += 1
            self._lit[lamp] = True
            active[lamp] = True

        elif pattern == "split":
            self._split_side ^= 1
            half = (n + 1) // 2
            if self._split_side == 0:
                active[:half] = True
            else:
                active[half:] = True
            if n == 1:
                active[0] = True

        return active

    def _random_lamp(self, exclude):
        n = self._zone_count
        if n == 1:
            return 0
        lamp = int(self._rng.integers(n - 1))
        if exclude is not None and lamp >= exclude % n:
            lamp += 1
        return lamp

    def _step(self, now):
        """Advance the pattern by one step."""
        self._step_count += 1
        self._lit_now = self._pick_lamps()

        mode = self.color_mode
        if mode == "cycle":
            self._color_point = (self._color_point + self.color_step) % 1.0
            self._zone_points[self._lit_now] = self._color_point
            self._zone_colors[self._lit_now] = self._palette(
                [self._color_point]
            )[0]
        elif mode == "random":
            self._zone_points[self._lit_now] = self._next_points(
                self._zone_points[self._lit_now]
            )
            self._zone_colors[self._lit_now] = self._palette(
                self._zone_points[self._lit_now]
            )
        elif mode == "per lamp":
            positions = self._lamp_positions()
            if self.pattern == "loop":
                # The palette walks along the lamps one lamp per step and
                # repeats `stages` times across the room
                positions = (
                    (np.arange(self._zone_count) + 0.5 + self._step_count)
                    * self.stages
                    / self._zone_count
                )
            self._zone_points = positions % 1.0
            self._zone_colors = self._palette(self._zone_points)

    # ------------------------------------------------------------- envelope

    def _strobe_level(self, elapsed, interval):
        """1.0 while a strobe flash is on, else 0.0."""
        flash_period = interval / self.strobe_flashes
        on_time = min(self.STROBE_ON_TIME, flash_period * 0.5)
        if elapsed >= interval:
            return 0.0
        return 1.0 if (elapsed % flash_period) < on_time else 0.0

    def _envelope_level(self, progress, elapsed, interval):
        """Brightness of a lit lamp at this point of the step."""
        envelope = self.envelope
        if envelope == "strobe":
            return self._strobe_level(elapsed, interval)
        if envelope == "hold":
            return 1.0
        if envelope == "fade":
            return max(0.0, 1.0 - progress)
        if envelope == "grow":
            return min(1.0, progress)
        if envelope == "glow":
            return float(np.sin(np.pi * min(1.0, progress)))
        if envelope == "flare":
            return max(0.0, 1.0 - 0.7 * progress)
        return 1.0

    def audio_data_updated(self, data):
        self._stepper.audio(data, timeit.default_timer())

    def render(self):
        now = self.now
        stepper = self._stepper

        if stepper.poll(now):
            self._step(now)

        elapsed = stepper.elapsed(now)
        interval = stepper.step_interval
        progress = min(1.0, elapsed / interval)
        level = self._envelope_level(progress, elapsed, interval)

        colors = self._zone_colors
        if self.envelope == "flare" and progress < self.FLARE_BLEND:
            blend = progress / self.FLARE_BLEND
            colors = self.flare_color * (1.0 - blend) + colors * blend

        # Every lamp starts on the backlight and the lit lamps blend
        # towards their colour by their level
        levels = np.zeros(self._zone_count)
        levels[self._lit_now] = level
        if self.pattern in ("fill", "scatter fill"):
            # Lamps filled by earlier steps stay on at full
            levels[self._lit & ~self._lit_now] = 1.0
        if self.pattern == "wave":
            phase = self._step_count + progress
            wave = 0.5 + 0.5 * np.sin(
                2.0 * np.pi * (self.stages * self._lamp_positions() - phase)
            )
            levels *= wave

        lamp_pixels = self.backlight * (1.0 - levels)[:, None] + colors * (
            levels[:, None]
        )
        self.pixels[:] = lamp_pixels[self._zone_of_pixel]
