"""True Strobe: a hard strobe with every lamp switching in the same frame."""

import math
import timeit

import numpy as np
import voluptuous as vol

from ledfx.color import parse_color, validate_color
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.utils.band_level import BandLevel, band_level_schema
from ledfx.effects.utils.layout import (
    LAYOUTS,
    anchors,
    angles,
    assign_channels,
    heading_vector,
    normalise,
    radii,
    resolve_positions,
    zone_map,
    zone_positions,
)
from ledfx.effects.utils.step_trigger import StepTrigger, step_trigger_schema


class TrueStrobeEffect(AudioReactiveEffect, GradientEffect):
    """
    A real strobe for a room of smart bulbs.

    The flashes run on a fixed clock at `rate` flashes per second and
    every lamp that takes part in a flash switches on in the same render
    frame and off again in the same frame, so bulbs and strip segments
    stay in perfect sync. The spread decides which lamps take part in a
    flash, worked out from the room positions of the lamps:

    - all:       every lamp, in sync
    - alternate: two interleaved groups by angle taking turns
    - halves:    front, back, right, left: the dividing line turns 90 deg
    - corners:   the next of `sectors` balanced channels around the room
    - sweep:     the next angular sector, going round the room
    - ripple:    rings from the centre outwards
    - scatter:   a random `density` fraction of the lamps
    - random:    one random lamp

    Colours come from a fixed strobe colour, the next palette colour per
    flash, the palette laid around the room by angle (a rainbow in 3D), or
    random palette colours per lamp. The gate runs the strobe continuously,
    in bursts of a few flashes on every step of the beat, or only while a
    frequency band is above a threshold.

    The timing uses the render clock, not the frame count, so an 8 Hz
    strobe at 30 frames per second still has clean on and off frames. A
    flash shorter than a frame is latched until it has been rendered once
    so no flash is ever lost. The rate is capped at 12 flashes per second,
    which is as fast as smart bulbs can follow.
    """

    NAME = "True Strobe"
    CATEGORY = "BPM"
    HIDDEN_KEYS = ["gradient_roll"]
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "zones",
        "color_step",
        "reactive_depth",
        "sensitivity",
    ]

    SPREADS = [
        "all",
        "alternate",
        "halves",
        "corners",
        "sweep",
        "ripple",
        "scatter",
        "random",
    ]
    COLOR_MODES = [
        "strobe color",
        "palette cycle",
        "palette by position",
        "palette random",
    ]
    GATES = ["always", "beat bursts", "level"]

    # Smart bulbs cannot follow anything faster than this many flashes a
    # second, whatever the settings say
    MAX_RATE = 12.0
    # A flash is never lit for more than this part of the time between two
    # flashes, so there is always a dark gap at least as long as the flash
    MAX_DUTY = 0.5
    # With at most this many pixels every pixel is treated as its own lamp
    AUTO_ZONE_PIXEL_LIMIT = 32
    # Zone count used for larger outputs (strips, matrices) when zones is 0
    AUTO_ZONE_COUNT = 8
    # Guard against a flash due exactly on a frame being missed by rounding
    INDEX_EPSILON = 1e-6
    # Headings of the dividing lines of the halves spread, in degrees
    HALF_HEADINGS = (0.0, 90.0)

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "rate",
                description="Flashes per second. Smart bulbs top out around 12 and look best at 8 to 10",
                default=8.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=12.0)),
            vol.Optional(
                "on_time",
                description="Seconds a flash stays lit, never more than half the time between two flashes",
                default=0.05,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.03, max=0.3)),
            vol.Optional(
                "spread",
                description="Which lamps take part in a flash: all in sync, alternate groups, turning halves, corners, a sweep round the room, rings from the centre, a random scatter or one random lamp",
                default="all",
            ): vol.In(SPREADS),
            vol.Optional(
                "color_mode",
                description="Where the flash colours come from: the strobe colour, the next palette colour per flash, the palette around the room by position, or random palette colours per lamp",
                default="strobe color",
            ): vol.In(COLOR_MODES),
            vol.Optional(
                "strobe_color",
                description="Colour of the flashes in strobe color mode",
                default="#FFFFFF",
            ): validate_color,
            vol.Optional(
                "gate",
                description="When the strobe runs: always, in bursts of flashes on every step, or only while the band level is above the threshold",
                default="always",
            ): vol.In(GATES),
            **step_trigger_schema(),
            vol.Optional(
                "burst_flashes",
                description="beat bursts: flashes on every step",
                default=4,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=16)),
            vol.Optional(
                "threshold",
                description="level: the band level above which the strobe runs",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            **band_level_schema(band="Bass", reactive_depth=0.0),
            vol.Optional(
                "density",
                description="scatter: the fraction of the lamps in every flash",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=1.0)),
            vol.Optional(
                "sectors",
                description="corners, sweep and ripple: how many groups the room is split into",
                default=4,
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=8)),
            vol.Optional(
                "tail",
                description="How much of the gap to the next flash the light fades out over. 0 is a hard off",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "background",
                description="Brightness of the lamp colours between flashes, so the show goes on between the flashes. 0 is black",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "layout",
                description="Where the lamps stand: Auto uses the device positions when known, otherwise a ring, line or grid",
                default="Auto",
            ): vol.In(LAYOUTS),
            vol.Optional(
                "color_step",
                description="palette cycle: how far along the palette the colour moves per flash. 0 keeps one colour",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "zones",
                description="Number of lamps / zones to split the output into. 0 = auto (one per pixel for bulbs)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=64)),
        }
    )

    # ---------------------------------------------------------- lifecycle

    def on_activate(self, pixel_count):
        now = timeit.default_timer()
        self._rng = np.random.default_rng()
        self._stepper = StepTrigger(self._config, now)
        self._level = BandLevel(self.band, self.sensitivity, now)
        self._flash_count = 0
        self._last_random = -1
        self._build_lamps(pixel_count)
        self._start_run(now)

    def config_updated(self, config):
        self.rate = min(float(config["rate"]), self.MAX_RATE)
        self.on_time = config["on_time"]
        self.spread = config["spread"]
        self.color_mode = config["color_mode"]
        self.strobe_color = np.array(
            parse_color(config["strobe_color"]), dtype=float
        )
        self.gate = config["gate"]
        self.burst_flashes = config["burst_flashes"]
        self.threshold = config["threshold"]
        self.band = config["band"]
        self.reactive_depth = config["reactive_depth"]
        self.sensitivity = config["sensitivity"]
        self.density = config["density"]
        self.sectors = config["sectors"]
        self.tail = config["tail"]
        self.background = config["background"]
        self.layout = config["layout"]
        self.color_step = config["color_step"]

        if getattr(self, "_stepper", None) is not None:
            self._stepper.configure(config)
        if getattr(self, "_level", None) is not None:
            self._level.configure(self.band, self.sensitivity)
        if getattr(self, "pixels", None) is None:
            return
        if self._lamp_key() != self._built_key:
            self._build_lamps(self.pixel_count)
        if self._run_key() != self._started_key:
            self._start_run(self.now)

    # ---------------------------------------------------------------- lamps

    def _lamp_key(self):
        return (
            self.layout,
            self._config["zones"],
            self.sectors,
            self.color_mode,
            self.pixel_count,
        )

    def _run_key(self):
        return (self.rate, self.gate, self.burst_flashes)

    def _build_lamps(self, pixel_count):
        """Map the pixels onto lamps and work out where every lamp stands."""
        self._zone_count, self._zone_of_pixel = zone_map(
            pixel_count,
            self._config["zones"],
            self.AUTO_ZONE_PIXEL_LIMIT,
            self.AUTO_ZONE_COUNT,
        )
        n = self._zone_count

        pixel_positions, source = resolve_positions(
            self.layout, pixel_count, self._virtual, self._ledfx
        )
        positions = normalise(
            zone_positions(pixel_positions, self._zone_of_pixel, n)
        )
        self._positions = positions
        self._position_source = source
        turns = angles(positions)
        # Rounding can put a lamp dead ahead a hair below a full turn
        self._angles = np.where(turns > 1.0 - 1e-9, 0.0, turns)
        self._angle_rank = self._ranks(self._angles)
        self._radius_rank = self._ranks(radii(positions))

        groups = max(1, min(self.sectors, n))
        self._groups = groups
        self._sweep_group = (self._angle_rank * groups) // n
        self._ripple_group = (self._radius_rank * groups) // n
        self._corner_channel = assign_channels(positions, anchors(groups))
        self._halves = []
        for heading in self.HALF_HEADINGS:
            x, y = heading_vector(heading)
            axis = np.array([[x, y, 0.0], [-x, -y, 0.0]])
            self._halves.append(assign_channels(positions, axis))

        self._lit = np.zeros(n, dtype=bool)
        self._lamp_colors = self._flash_colors()
        self._built_key = self._lamp_key()

    @staticmethod
    def _ranks(values):
        """Rank of every value in ascending order, ties in index order."""
        order = np.argsort(values, kind="stable")
        ranks = np.empty(len(values), dtype=int)
        ranks[order] = np.arange(len(values))
        return ranks

    # ---------------------------------------------------------------- audio

    def audio_data_updated(self, data):
        now = timeit.default_timer()
        self._stepper.audio(data, now)
        melbanks = data.melbanks
        self._level.update(
            melbanks.melbanks[-1],
            melbanks.melbank_processors[-1].melbank_frequencies,
            now,
        )

    # --------------------------------------------------------------- timing

    def _period(self):
        """Seconds between two flashes."""
        return 1.0 / max(1.0, min(self.rate, self.MAX_RATE))

    def _on_seconds(self, period=None):
        """Seconds a flash stays lit, clamped to half the period."""
        if period is None:
            period = self._period()
        return min(self.on_time, period * self.MAX_DUTY)

    def _start_run(self, now):
        """Start a run of flashes: unlimited, or a burst on a step."""
        self._origin = now
        self._run_flashes = (
            self.burst_flashes if self.gate == "beat bursts" else None
        )
        self._last_index = -1
        self._flash_index = -1
        self._flash_start = -np.inf
        self._rendered = True
        self._lit = np.zeros(self._zone_count, dtype=bool)
        self._started_key = self._run_key()

    def _due_index(self, now, period):
        """Index of the latest flash due in the current run, -1 for none."""
        elapsed = now - self._origin
        if elapsed < 0.0:
            return -1
        index = int(math.floor(elapsed / period + self.INDEX_EPSILON))
        if self._run_flashes is not None:
            index = min(index, self._run_flashes - 1)
        return index

    def _gate_open(self):
        if self.gate == "level":
            return self._level.level > self.threshold
        return True

    def _next_due(self, period):
        """When the flash after the current one is expected."""
        if (
            self._run_flashes is not None
            and self._flash_index >= self._run_flashes - 1
        ):
            # The last flash of a burst: the next one comes with the next step
            return self._origin + self._stepper.step_interval
        return self._flash_start + period

    def _flash_level(self, now, on, period):
        """Brightness of the lamps of the current flash, 0 to 1."""
        if not self._lit.any():
            return 0.0
        if not self._rendered:
            # Latch: a flash always shows for at least one frame
            self._rendered = True
            return 1.0
        age = now - self._flash_start
        if age < on:
            return 1.0
        if self.tail <= 0.0:
            return 0.0
        fade = self.tail * (self._next_due(period) - self._flash_start - on)
        if fade <= 0.0:
            return 0.0
        return float(np.clip(1.0 - (age - on) / fade, 0.0, 1.0))

    # -------------------------------------------------------------- flashes

    def _flash_lamps(self, index):
        """Which lamps take part in flash number index of the run."""
        n = self._zone_count
        spread = self.spread
        lit = np.zeros(n, dtype=bool)
        if n == 1 or spread == "all":
            lit[:] = True
        elif spread == "alternate":
            lit = self._angle_rank % 2 == index % 2
        elif spread == "halves":
            axis = (index // 2) % len(self._halves)
            lit = self._halves[axis] == index % 2
        elif spread == "corners":
            lit = self._corner_channel == index % self._groups
        elif spread == "sweep":
            lit = self._sweep_group == index % self._groups
        elif spread == "ripple":
            lit = self._ripple_group == index % self._groups
        elif spread == "scatter":
            count = max(1, min(n, int(round(self.density * n))))
            lit[self._rng.choice(n, count, replace=False)] = True
        elif spread == "random":
            if 0 <= self._last_random < n:
                # Any lamp but the one of the previous flash
                lamp = int(self._rng.integers(n - 1))
                if lamp >= self._last_random:
                    lamp += 1
            else:
                lamp = int(self._rng.integers(n))
            self._last_random = lamp
            lit[lamp] = True
        return lit

    def _flash_colors(self):
        """The colour every lamp would show in the next flash, (n, 3)."""
        n = self._zone_count
        mode = self.color_mode
        if mode == "palette cycle":
            point = (self._flash_count * self.color_step) % 1.0
            return np.tile(
                self.get_gradient_color_vectorized1d(np.array([point]))[0],
                (n, 1),
            )
        if mode == "palette by position":
            return self.get_gradient_color_vectorized1d(self._angles)
        if mode == "palette random":
            return self.get_gradient_color_vectorized1d(self._rng.random(n))
        return np.tile(self.strobe_color, (n, 1))

    def _start_flash(self, index, start):
        """Light the lamps of a flash: they all switch in this frame."""
        self._lit = self._flash_lamps(index)
        colors = self._flash_colors()
        if self.color_mode == "palette by position":
            self._lamp_colors = colors
        else:
            self._lamp_colors[self._lit] = colors[self._lit]
        self._flash_index = index
        self._flash_start = start
        self._rendered = False
        self._flash_count += 1

    # --------------------------------------------------------------- render

    def render(self):
        now = self.now
        if self._stepper.poll(now) and self.gate == "beat bursts":
            self._start_run(now)

        period = self._period()
        index = self._due_index(now, period)
        if index > self._last_index:
            self._last_index = index
            if self._gate_open():
                self._start_flash(index, self._origin + index * period)

        level = self._flash_level(now, self._on_seconds(period), period)
        brightness = self._lit * level
        if self.background > 0.0:
            brightness = self.background + (1.0 - self.background) * brightness
        brightness = brightness * self._level.scale(self.reactive_depth)
        out = self._lamp_colors * brightness[:, None]
        self.pixels[:] = out[self._zone_of_pixel]
