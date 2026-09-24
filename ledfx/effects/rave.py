"""Rave / party mode effect for a handful of lamps (Hue, LIFX, Nanoleaf...)."""

import timeit

import numpy as np
import voluptuous as vol

from ledfx.color import parse_color, validate_color
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect


class RaveEffect(AudioReactiveEffect, GradientEffect):
    """
    Party mode in the style of the "disco" / "party" modes found in smart
    bulb apps.

    The output is treated as a small number of independent lamps ("zones")
    rather than a continuous strip. Every step the lamps snap to new colours
    from the palette. Steps are driven by the beat tracker, bass hits, onsets
    or a plain timer, and the timer takes over automatically when no beat has
    been heard for a while so the party keeps going between tracks.

    Built for smart bulb setups such as a Philips Hue entertainment zone,
    where every pixel is a whole lamp, but it works on strips and matrices as
    well by splitting them into zones.
    """

    NAME = "Rave"
    CATEGORY = "BPM"
    HIDDEN_KEYS = ["gradient_roll"]
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "zones",
        "flash_chance",
        "strobe_color",
        "strobe_flashes",
    ]

    MODES = ["random", "wash", "chase", "alternate", "strobe"]
    TRIGGERS = ["Beat", "Bass hit", "Onset", "Timer"]
    STEP_MAPPINGS = {
        "1/4": 0.25,
        "1/2": 0.5,
        "1": 1.0,
        "2": 2.0,
        "4": 4.0,
    }

    # Seconds without an audio trigger before the timer takes over
    SILENCE_TIMEOUT = 5.0
    # Minimum distance along the palette between a lamp's old and new colour,
    # so that every step is a visible change
    MIN_PALETTE_STEP = 0.15
    # With at most this many pixels every pixel is treated as its own lamp
    AUTO_ZONE_PIXEL_LIMIT = 32
    # Zone count used for larger outputs (strips, matrices) when zones is 0
    AUTO_ZONE_COUNT = 8
    # Longest a single strobe flash stays on, in seconds
    STROBE_ON_TIME = 0.05
    # Bounds for the measured step interval used by fade and strobe timing
    MIN_STEP_INTERVAL = 0.05
    MAX_STEP_INTERVAL = 10.0

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "mode",
                description="Party pattern: random colours per lamp, one colour wash, chase, alternating pairs or strobe",
                default="random",
            ): vol.In(MODES),
            vol.Optional(
                "trigger",
                description="What advances the pattern. Timer takes over automatically when no beat is heard",
                default="Beat",
            ): vol.In(TRIGGERS),
            vol.Optional(
                "steps_per_beat",
                description="Colour changes per beat (below 1 = one change every few beats)",
                default="1",
            ): vol.In(list(STEP_MAPPINGS.keys())),
            vol.Optional(
                "timer_bpm",
                description="Tempo for the Timer trigger, also used while no beat is heard",
                default=128,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=300)),
            vol.Optional(
                "fade",
                description="How much of each step the lamps fade out. 0 holds the colour until the next step",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "zones",
                description="Number of lamps / zones to split the output into. 0 = auto (one per pixel for bulbs)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=64)),
            vol.Optional(
                "flash_chance",
                description="Chance that a step is a full flash of the strobe colour instead of palette colours",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "strobe_color",
                description="Colour used by strobe mode and by accent flashes",
                default="#FFFFFF",
            ): validate_color,
            vol.Optional(
                "strobe_flashes",
                description="Flashes per step in strobe mode",
                default=3,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
        }
    )

    def on_activate(self, pixel_count):
        """Reset all runtime state once the pixel count is known."""
        now = timeit.default_timer()
        self._rng = np.random.default_rng()
        self._step_pending = False
        self._last_step_time = now
        self._step_interval = self.timer_interval
        # Start with the timer running so the lamps move straight away, the
        # first real beat hands control over to the audio trigger.
        self._last_audio_trigger = now - self.SILENCE_TIMEOUT
        self._last_phase = 0.0
        self._chase_index = -1
        self._alt_phase = 0
        self._pair_point = self._rng.random()
        self._flash = False
        self._zone_points = None
        self._zone_colors = None
        self._build_zones(pixel_count)
        # Light something up immediately instead of waiting for the first step
        self._step(now)

    def config_updated(self, config):
        """Cache validated config values and rebuild zones when needed."""
        self.mode = self._config["mode"]
        self.trigger = self._config["trigger"]
        self.steps_per_beat = self.STEP_MAPPINGS[
            self._config["steps_per_beat"]
        ]
        self.timer_interval = (
            60.0 / self._config["timer_bpm"] / self.steps_per_beat
        )
        self.fade = self._config["fade"]
        self.flash_chance = self._config["flash_chance"]
        self.strobe_flashes = self._config["strobe_flashes"]
        self.strobe_color = np.array(
            parse_color(self._config["strobe_color"]), dtype=float
        )

        if getattr(self, "pixels", None) is not None:
            self._build_zones(self.pixel_count)

    def _build_zones(self, pixel_count):
        """Map pixels onto zones, keeping the colours of zones that survive."""
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
        self._chase_index %= zones

    def _palette(self, points):
        """Look up palette colours, shape (N, 3), for points in [0, 1]."""
        return self.get_gradient_color_vectorized1d(np.asarray(points))

    def _next_points(self, points):
        """Move each point along the palette by a random, clearly visible amount."""
        shift = self._rng.uniform(
            self.MIN_PALETTE_STEP,
            1.0 - self.MIN_PALETTE_STEP,
            size=len(points),
        )
        return (points + shift) % 1.0

    def _step(self, now):
        """Advance the pattern by one step."""
        interval = now - self._last_step_time
        if self.MIN_STEP_INTERVAL < interval < self.MAX_STEP_INTERVAL:
            self._step_interval = interval
        self._last_step_time = now

        mode = self.mode
        self._flash = (
            mode != "strobe"
            and self.flash_chance > 0
            and self._rng.random() < self.flash_chance
        )

        if mode == "random":
            self._zone_points = self._next_points(self._zone_points)
            self._zone_colors = self._palette(self._zone_points)

        elif mode == "wash":
            point = self._next_points(self._zone_points[:1])
            self._zone_points[:] = point
            self._zone_colors[:] = self._palette(point)

        elif mode == "chase":
            self._chase_index = (self._chase_index + 1) % self._zone_count
            point = self._next_points(self._zone_points[:1])
            self._zone_points[:] = point
            self._zone_colors[:] = 0.0
            self._zone_colors[self._chase_index] = self._palette(point)[0]

        elif mode == "alternate":
            if self._alt_phase == 0:
                # New pair of colours from opposite ends of the palette
                self._pair_point = self._next_points(
                    np.array([self._pair_point])
                )[0]
            self._alt_phase ^= 1
            pair = self._pair_colors()
            self._zone_colors[0::2] = pair[self._alt_phase]
            self._zone_colors[1::2] = pair[1 - self._alt_phase]

        elif mode == "strobe":
            self._zone_colors[:] = self.strobe_color

        if self._flash:
            self._zone_colors[:] = self.strobe_color

    def _pair_colors(self):
        """Two palette colours half a palette apart for alternate mode."""
        point = self._pair_point
        for _ in range(4):
            pair = self._palette([point, (point + 0.5) % 1.0])
            if not np.allclose(pair[0], pair[1]):
                break
            # Hard edged palettes (red | blue) can land both points on the
            # same side of a stop, nudge along and try again
            point = (point + 0.05) % 1.0
        self._pair_point = point
        return pair

    def _strobe_level(self, elapsed, interval):
        """Return 1.0 while a strobe flash is on, else 0.0."""
        flash_period = interval / self.strobe_flashes
        on_time = min(self.STROBE_ON_TIME, flash_period * 0.5)
        return 1.0 if (elapsed % flash_period) < on_time else 0.0

    def audio_data_updated(self, data):
        trigger = self.trigger
        if trigger == "Timer":
            return

        now = timeit.default_timer()

        if trigger == "Beat":
            beat = data.bpm_beat_now()
            if beat:
                self._last_audio_trigger = now
            if now - self._last_audio_trigger > self.SILENCE_TIMEOUT:
                # Nothing to lock onto, the timer in render() takes over
                return
            # Quantise the bar oscillator into steps so sub beat and multi
            # beat rates stay in time with the music. A detected beat is
            # always a step boundary at one or more steps per beat.
            phase = data.bar_oscillator() * self.steps_per_beat
            if (
                (beat and self.steps_per_beat >= 1)
                or int(phase) != int(self._last_phase)
                or phase < self._last_phase
            ):
                self._step_pending = True
            self._last_phase = phase

        elif trigger == "Bass hit":
            if data.volume_beat_now():
                self._last_audio_trigger = now
                self._step_pending = True

        elif trigger == "Onset":
            if data.onset():
                self._last_audio_trigger = now
                self._step_pending = True

    def render(self):
        now = self.now

        if (
            self.trigger == "Timer"
            or now - self._last_audio_trigger > self.SILENCE_TIMEOUT
        ):
            if now - self._last_step_time >= self.timer_interval:
                self._step_pending = True

        if self._step_pending:
            self._step_pending = False
            self._step(now)

        elapsed = now - self._last_step_time
        if self.mode == "strobe":
            level = self._strobe_level(elapsed, self._step_interval)
        elif self.fade > 0 and not self._flash:
            level = max(0.0, 1.0 - elapsed / (self.fade * self._step_interval))
        elif self._flash:
            # Accent flashes always fade so they read as a hit, not a hold
            level = max(0.0, 1.0 - elapsed / (0.5 * self._step_interval))
        else:
            level = 1.0

        self.pixels[:] = self._zone_colors[self._zone_of_pixel] * level
