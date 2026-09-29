"""Orbit: colour fields that turn, flow and scatter around the room by position."""

import math
import timeit

import numpy as np
import voluptuous as vol
from pyfastnoiselite import pyfastnoiselite as fnl

from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.utils.band_level import BandLevel, band_level_schema
from ledfx.effects.utils.flash_limiter import FlashLimiter
from ledfx.effects.utils.layout import (
    LAYOUTS,
    anchors,
    angles,
    assign_channels,
    normalise,
    project,
    radii,
    resolve_positions,
    synthetic_positions,
    zone_map,
    zone_positions,
)
from ledfx.effects.utils.sections import SectionDetector
from ledfx.effects.utils.step_trigger import StepTrigger, step_trigger_schema


class OrbitEffect(AudioReactiveEffect, GradientEffect):
    """
    Spatial show engine: every lamp is coloured by where it stands in the
    room and a colour field moves over the room, so the whole room turns,
    flows, floods or scatters as one.

    The positions come from the device when it knows them (a Hue
    entertainment zone stores x, y, z per channel) and from a ring, line
    or grid otherwise, so strips and matrices turn too. The plane setting
    picks which two axes the field turns in: the floor, the front wall or
    a side wall, so a room can also turn vertically.

    Modes:

    - swirl:   the palette wrapped around the room by angle, turning
    - beacon:  bright lobes turning, the colour drifting the other way
    - sectors: hard or soft palette wedges turning
    - wave:    the palette flowing along a heading
    - ripple:  the palette flowing out of, or into, the centre
    - sweep:   a new palette colour floods the room along a heading per step
    - halves:  a two colour split turning per step, or smoothly
    - corners: balanced channels around the room lit one per step
    - noise:   a drifting three dimensional noise field over the lamps
    - scatter: random clusters of lamps lit per step, in three dimensions
    - auto:    rotates through the modes

    The continuous modes complete one turn, one wave cycle or one noise
    drift unit every beats_per_turn beats of the measured tempo; the
    stepped modes advance on every step of the trigger. With reactive
    depth above zero the brightness follows the level of a frequency
    band, and a flash limiter keeps any lamp from jumping to bright more
    often than about three times a second.
    """

    NAME = "Orbit"
    CATEGORY = "BPM"
    HIDDEN_KEYS = ["gradient_roll"]
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "zones",
        "auto_steps",
        "auto_sections",
        "color_step",
        "sensitivity",
        "flash_limit",
    ]

    MODES = [
        "auto",
        "swirl",
        "beacon",
        "sectors",
        "wave",
        "ripple",
        "sweep",
        "halves",
        "corners",
        "noise",
        "scatter",
    ]
    AUTO_MODES = MODES[1:]
    # What auto mode picks from in the loud and the quiet sections of a
    # track when it follows the sections; soft sections pick from all
    AUTO_LOUD_MODES = [
        "beacon",
        "sectors",
        "sweep",
        "halves",
        "corners",
        "scatter",
    ]
    AUTO_QUIET_MODES = ["swirl", "wave", "ripple", "noise"]
    STEPPED_MODES = ("sweep", "halves", "corners", "scatter")
    SPINS = ["clockwise", "counter", "alternate", "random"]
    PLANES = ["floor", "front wall", "side wall"]

    # With at most this many pixels every pixel is its own lamp
    AUTO_ZONE_PIXEL_LIMIT = 32
    # A matrix keeps one lamp per pixel up to this many, so the field
    # shows as a picture on it
    AUTO_MATRIX_PIXEL_LIMIT = 1024
    # Zone count for long strips when zones is 0
    AUTO_ZONE_COUNT = 8
    # Lamps closer than this to the centre ride along with the pattern
    CENTRE_RADIUS = 0.05
    # Lowest softness used in the edge blends, so a hard edge stays a step
    MIN_SOFTNESS = 0.02
    # Beacon: the colour field drifts against the turn at this share of
    # the turning speed
    BEACON_DRIFT = 0.75
    # Noise: radius of the sampling orbit in noise wavelengths, its rise
    # along the third axis per drift unit, and the gain on the raw value
    NOISE_ORBIT_RADIUS = 1.0
    NOISE_RISE = 0.25
    NOISE_GAIN = 1.25
    # Smallest palette jump when a random colour is picked
    MIN_PALETTE_STEP = 0.15

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "mode",
                description="How the colour field moves over the room, or auto to rotate through the modes",
                default="swirl",
            ): vol.In(MODES),
            vol.Optional(
                "layout",
                description="Where the lamps stand: Auto takes the device positions when it knows them and a ring otherwise",
                default="Auto",
            ): vol.In(LAYOUTS),
            **step_trigger_schema(
                trigger="Beat", steps_per_beat="1", timer_bpm=120
            ),
            vol.Optional(
                "beats_per_turn",
                description="Beats for one turn of the field, one wave cycle or one noise drift unit",
                default=8,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=64)),
            vol.Optional(
                "spin",
                description="Which way the field turns or flows: clockwise, counter, alternate per turn or event, or random",
                default="clockwise",
            ): vol.In(SPINS),
            vol.Optional(
                "heading",
                description="Direction of wave, sweep and halves in degrees: 0 towards the front, 90 towards the right",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=359)),
            vol.Optional(
                "heading_step",
                description="Degrees the heading turns per event for sweep and halves: 180 flips, 90 quarters, 0 keeps it (halves then turn smoothly)",
                default=90,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=359)),
            vol.Optional(
                "sectors",
                description="Palette repeats for swirl, lobes for beacon, wedges for sectors, channels for corners, clusters for scatter, terraces for noise",
                default=1,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=8)),
            vol.Optional(
                "softness",
                description="Trough darkness for swirl, wave and ripple, edge blend for beacon, sectors, halves, sweep and noise, fade share of the step for corners and scatter",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "wavelength",
                description="Length of one palette cycle in room lengths for wave and ripple, feature size for noise",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.25, max=4.0)),
            vol.Optional(
                "radius",
                description="scatter: reach of every cluster, 1 is half the room",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=2.0)),
            vol.Optional(
                "plane",
                description="Which two axes the field turns in when the device knows its positions: the floor, the front wall or a side wall",
                default="floor",
            ): vol.In(PLANES),
            **band_level_schema(),
            vol.Optional(
                "background",
                description="Brightness of the field colour on the lamps that are not lit",
                default=0.15,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "flash_limit",
                description="Keep any lamp from jumping to bright more than about three times a second",
                default=True,
            ): bool,
            vol.Optional(
                "zones",
                description="Number of lamps / zones to split the output into. 0 = auto (one per pixel for bulbs and matrices)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=256)),
            vol.Optional(
                "auto_steps",
                description="Steps between mode changes in auto mode",
                default=32,
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=128)),
            vol.Optional(
                "auto_sections",
                description="In auto mode follow the loud, soft and quiet sections of the music: hard modes when loud, soft ones when quiet, a new mode on every drop and a palette shift every few seconds",
                default=True,
            ): bool,
            vol.Optional(
                "color_step",
                description="How far along the palette the colour moves per event for sweep, halves, corners and scatter. 0 picks random palette colours",
                default=0.15,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        }
    )

    # ---------------------------------------------------------- lifecycle

    def on_activate(self, pixel_count):
        now = timeit.default_timer()
        self._rng = np.random.default_rng()
        self._stepper = StepTrigger(self._config, now)
        self._band = BandLevel(self.band, self.sensitivity, now)
        self._sections = SectionDetector(now)
        self._drop_pending = False
        self._last_time = now
        self._build_noise(int(self._rng.integers(1, 2**31)))
        self._build_geometry(pixel_count)
        self._limiter = FlashLimiter(self._zone_count, self.flash_limit)
        self._mode_key = self.mode_config
        self._reset_state(now)

    def config_updated(self, config):
        c = self._config
        self.mode_config = c["mode"]
        self.layout = c["layout"]
        self.beats_per_turn = int(c["beats_per_turn"])
        self.spin = c["spin"]
        self.heading = float(c["heading"])
        self.heading_step = float(c["heading_step"])
        self.sectors = int(c["sectors"])
        self.softness = float(c["softness"])
        self.wavelength = float(c["wavelength"])
        self.radius = float(c["radius"])
        self.plane = c["plane"]
        self.band = c["band"]
        self.reactive_depth = float(c["reactive_depth"])
        self.sensitivity = float(c["sensitivity"])
        self.background = float(c["background"])
        self.flash_limit = bool(c["flash_limit"])
        self.auto_steps = int(c["auto_steps"])
        self.auto_sections = bool(c["auto_sections"])
        self.color_step = float(c["color_step"])

        if getattr(self, "_stepper", None) is not None:
            self._stepper.configure(c)
        if getattr(self, "_band", None) is not None:
            self._band.configure(self.band, self.sensitivity)
        if getattr(self, "_limiter", None) is not None:
            self._limiter.enabled = self.flash_limit
        if getattr(self, "pixels", None) is None or not hasattr(
            self, "_geometry_key"
        ):
            return

        now = timeit.default_timer()
        if self._geometry_key != self._current_geometry_key():
            # The lamps moved: everything that refers to them starts over
            self._build_geometry(self.pixel_count)
            self._limiter.reset(self._zone_count)
            self._mode_key = self.mode_config
            self._reset_state(now)
            return
        if self._channel_key != (self.sectors, self.heading):
            self._build_channels()
        if self._mode_key != self.mode_config:
            self._mode_key = self.mode_config
            self._reset_state(now)

    # ------------------------------------------------------------- geometry

    def _current_geometry_key(self):
        return (self.layout, self.plane, int(self._config["zones"]))

    def _build_geometry(self, pixel_count):
        self._build_zones(pixel_count)
        self._resolve_layout()
        self._build_channels()
        self._geometry_key = self._current_geometry_key()

    def _virtual_rows(self):
        try:
            return int(getattr(self._virtual, "rows", 1) or 1)
        except Exception:
            return 1

    def _build_zones(self, pixel_count):
        zones = int(self._config["zones"])
        if (
            zones <= 0
            and self._virtual_rows() > 1
            and pixel_count <= self.AUTO_MATRIX_PIXEL_LIMIT
        ):
            # A matrix keeps one lamp per pixel so the field shows on it
            zones = pixel_count
        self._zone_count, self._zone_of_pixel = zone_map(
            pixel_count,
            zones,
            self.AUTO_ZONE_PIXEL_LIMIT,
            self.AUTO_ZONE_COUNT,
        )

    def _resolve_layout(self):
        """Where every zone stands, in the turning plane and in 3D."""
        count = self.pixel_count
        positions, source = resolve_positions(
            self.layout, count, self._virtual, self._ledfx
        )
        if source == "device":
            if self._zone_count != count:
                positions = zone_positions(
                    positions, self._zone_of_pixel, self._zone_count
                )
        else:
            # A synthetic layout is laid over the zones themselves
            positions, source = synthetic_positions(
                self.layout, self._zone_count, self._virtual_rows()
            )
        self._source = source
        self._positions = np.asarray(positions, dtype=float)
        # Full three dimensional positions, for noise and scatter
        self._space = np.round(normalise(self._positions), 9)
        # The two turning axes in x and y, the third in z
        self._plane_positions = np.round(
            normalise(self._pick_plane(self._positions)), 9
        )
        self._angles = angles(self._plane_positions)
        self._radii = radii(self._plane_positions)
        self._centre = self._radii < self.CENTRE_RADIUS

    def _pick_plane(self, positions):
        """Reorder the axes so the chosen plane lands in x and y."""
        positions = np.asarray(positions, dtype=float)
        if self._source != "device":
            # Synthetic layouts already lie in the turning plane
            return positions
        x, y, z = positions[:, 0], positions[:, 1], positions[:, 2]
        if self.plane == "front wall":
            return np.stack([x, z, y], axis=1)
        if self.plane == "side wall":
            return np.stack([y, z, x], axis=1)
        return positions

    def _build_channels(self):
        """Balanced channels around anchor points turned by the heading."""
        count = max(1, min(self.sectors, self._zone_count))
        points = anchors(count)
        turn = math.radians(self.heading)
        x, y = points[:, 0].copy(), points[:, 1].copy()
        points[:, 0] = x * math.cos(turn) + y * math.sin(turn)
        points[:, 1] = y * math.cos(turn) - x * math.sin(turn)
        self._channels = assign_channels(self._plane_positions, points)
        self._channel_count = count
        self._channel_key = (self.sectors, self.heading)
        if getattr(self, "_channel", None) is not None:
            self._channel %= count

    def _build_noise(self, seed):
        self._noise_seed = int(seed)
        noise = fnl.FastNoiseLite(seed=self._noise_seed)
        noise.noise_type = fnl.NoiseType.NoiseType_OpenSimplex2
        noise.frequency = 1.0
        self._noise = noise

    # ---------------------------------------------------------------- state

    def _reset_state(self, now):
        """Start the field over, keeping the beat clock and the lamps."""
        self._phase = 0.0
        self._turn = 0.0
        self._direction = -1.0 if self.spin == "counter" else 1.0
        self._step_count = 0
        self._event = 0
        self._point = 0.0
        self._sweep_old = 0.0
        self._sweep_new = 0.0
        self._heading_offset = 0.0
        self._channel = -1
        self._channel_dir = 1
        self._cluster_lamps = []
        self._cluster_centres = np.zeros((0, 3))
        self._cluster_points = np.zeros(0)
        self._auto_mode = None
        self._palette_shift = 0.0
        if self.mode_config == "auto":
            self._auto_mode = self._auto_choice(None)
        self._step(now)

    @property
    def mode(self):
        """The mode being rendered, resolved from auto."""
        if self.mode_config == "auto":
            return self._auto_mode
        return self.mode_config

    def _auto_choice(self, current, section=None):
        """The next auto mode, by the section of the music when known."""
        options = self.AUTO_MODES
        if self.auto_sections:
            if section is None and getattr(self, "_sections", None):
                section = self._sections.section
            if section == "loud":
                options = self.AUTO_LOUD_MODES
            elif section == "quiet":
                options = self.AUTO_QUIET_MODES
        options = [mode for mode in options if mode != current]
        if not options:
            options = [mode for mode in self.AUTO_MODES if mode != current]
        return options[int(self._rng.integers(len(options)))]

    def _switch_auto(self, section=None):
        """Change the auto mode now and start its events afresh."""
        self._auto_mode = self._auto_choice(self._auto_mode, section)
        self._event = 0
        self._channel = -1
        self._step_count = 0

    def _next_point(self):
        """The next palette position for an event."""
        if self.color_step > 0.0:
            self._point = (self._point + self.color_step) % 1.0
        else:
            self._point = (
                self._point
                + self._rng.uniform(
                    self.MIN_PALETTE_STEP, 1.0 - self.MIN_PALETTE_STEP
                )
            ) % 1.0
        return self._point

    def _event_sign(self, event):
        """Direction of a stepped event: +1 clockwise, -1 counter."""
        if self.spin == "counter":
            return -1.0
        if self.spin == "alternate":
            return 1.0 if event % 2 == 0 else -1.0
        if self.spin == "random":
            return 1.0 if self._rng.random() < 0.5 else -1.0
        return 1.0

    # ---------------------------------------------------------------- steps

    def _step(self, now):
        """One event: the stepped modes advance, auto mode may switch."""
        self._step_count += 1
        if (
            self.mode_config == "auto"
            and self._step_count % self.auto_steps == 0
        ):
            self._switch_auto()
        event = self._event
        self._event += 1
        mode = self.mode

        if mode == "sweep":
            self._sweep_old = self._sweep_new
            self._sweep_new = self._next_point()
            self._turn_heading(event)

        elif mode == "halves":
            self._next_point()
            if self.heading_step > 0:
                self._turn_heading(event)

        elif mode == "corners":
            self._channel = self._next_channel(event)
            self._next_point()

        elif mode == "scatter":
            self._scatter_clusters()

    def _turn_heading(self, event):
        if self.spin == "random":
            self._heading_offset = float(self._rng.uniform(0.0, 360.0))
        elif event > 0:
            self._heading_offset += self.heading_step * self._event_sign(event)
        self._heading_offset %= 360.0

    def _next_channel(self, event):
        count = self._channel_count
        current = self._channel
        if count <= 1:
            return 0
        if self.spin == "random":
            pick = int(self._rng.integers(count - 1))
            if current >= 0 and pick >= current:
                pick += 1
            return pick
        if self.spin == "alternate":
            if current < 0:
                return 0
            following = current + self._channel_dir
            if following < 0 or following >= count:
                self._channel_dir = -self._channel_dir
                following = current + self._channel_dir
            return int(following)
        return int((current + self._event_sign(event)) % count)

    def _scatter_clusters(self):
        """Pick the cluster centres of this event among the lamps."""
        n = self._zone_count
        count = max(1, min(self.sectors, n))
        previous = set(self._cluster_lamps)
        choices = [lamp for lamp in range(n) if lamp not in previous]
        if len(choices) < count:
            choices = list(range(n))
        lamps = self._rng.choice(choices, size=count, replace=False)
        self._cluster_lamps = [int(lamp) for lamp in lamps]
        self._cluster_centres = self._space[self._cluster_lamps]
        self._cluster_points = np.array(
            [self._next_point() for _ in range(count)]
        )

    # ---------------------------------------------------------------- audio

    def audio_data_updated(self, data):
        now = timeit.default_timer()
        self._stepper.audio(data, now)
        melbanks = data.melbanks
        melbank = melbanks.melbanks[-1]
        self._band.update(
            melbank,
            melbanks.melbank_processors[-1].melbank_frequencies,
            now,
        )
        if self.auto_sections and self.mode_config == "auto":
            phase = data.bar_oscillator()
            if not isinstance(phase, (int, float)):
                phase = None
            raw = float(
                np.mean(np.nan_to_num(np.asarray(melbank, dtype=float)))
            )
            self._sections.update(raw, now, phase)
            if self._sections.drop:
                self._drop_pending = True
            if self._sections.palette_changed:
                self._palette_shift = self._sections.palette_offset

    # ----------------------------------------------------------------- field

    def _advance(self, dt):
        """Move the continuous phase by dt seconds, beat synced."""
        delta = dt / (self._stepper.beat_period() * self.beats_per_turn)
        self._phase += self._direction * delta
        self._turn += delta
        if self._turn >= 1.0:
            self._turn %= 1.0
            if self.spin == "alternate":
                self._direction = -self._direction
            elif self.spin == "random":
                self._direction = 1.0 if self._rng.random() < 0.5 else -1.0

    def _palette(self, points):
        """Palette colours, (n, 3) in 0..255, for points anywhere on the line."""
        points = np.mod(
            np.asarray(points, dtype=float) + self._palette_shift, 1.0
        )
        return self.get_gradient_color_vectorized1d(points)

    def _palette_one(self, point):
        return self._palette(np.array([point]))[0]

    def _turn_angles(self):
        """Angle of every lamp relative to the turning pattern, in turns."""
        a = self._angles.copy()
        # A lamp at the centre has no angle: it rides with the pattern
        a[self._centre] = self._phase
        return a - self._phase

    def _along(self, heading):
        """Position of every lamp along a heading, 0 at the back end, 1 at the front end."""
        p = project(self._plane_positions, heading)
        low, high = float(p.min()), float(p.max())
        span = high - low
        if span < 1e-9:
            return np.zeros(len(p))
        return (p - low) / span

    def _trough(self, t):
        """Brightness along a palette cycle: full at 0, darkest at half a cycle."""
        return 1.0 - self.softness * (0.5 - 0.5 * np.cos(2.0 * np.pi * t))

    def _terrace(self, t, count):
        """Quantise palette positions into count steps, blended by softness."""
        s = max(self.MIN_SOFTNESS, self.softness)
        scaled = t * count
        w = np.floor(scaled)
        f = scaled - w
        return (w + 0.5 + np.clip((f - 0.5) / s, -0.5, 0.5)) / count

    def _hold_then_fade(self, progress):
        """Envelope of a stepped event: hold, then fade over softness of the step."""
        hold = 1.0 - self.softness
        if progress <= hold:
            return 1.0
        return float(
            np.clip(1.0 - (progress - hold) / max(1e-6, self.softness), 0, 1)
        )

    def _noise_values(self):
        """The noise field at every lamp, 0..1, drifting with the phase."""
        scale = 1.0 / (2.0 * self.wavelength)
        orbit = self._phase
        offset = np.array(
            [
                self.NOISE_ORBIT_RADIUS * math.cos(orbit),
                self.NOISE_ORBIT_RADIUS * math.sin(orbit),
                self.NOISE_RISE * self._phase,
            ]
        )
        coords = np.ascontiguousarray(
            (self._space * scale + offset).T, dtype=np.float32
        )
        values = np.asarray(self._noise.gen_from_coords(coords), dtype=float)
        values = np.nan_to_num(values.reshape(-1))
        return np.clip(0.5 + 0.5 * self.NOISE_GAIN * values, 0.0, 1.0)

    def _field(self, now):
        """
        The field of this frame: the lit colour and brightness of every
        lamp, and the field colour its dimmed background shows.
        """
        n = self._zone_count
        mode = self.mode
        phase = self._phase
        ones = np.ones(n)

        if mode == "swirl":
            t = self._turn_angles() * self.sectors
            colours = self._palette(t)
            return colours, self._trough(t), colours

        if mode == "beacon":
            d = np.mod(self._turn_angles() * self.sectors, 1.0)
            u = 4.0 * np.minimum(d, 1.0 - d)
            s = max(self.MIN_SOFTNESS, self.softness)
            lit = np.clip((1.0 - u) / s, 0.0, 1.0)
            colours = self._palette(self._angles + self.BEACON_DRIFT * phase)
            return colours, lit, colours

        if mode == "sectors":
            t = np.mod(self._turn_angles(), 1.0)
            colours = self._palette(self._terrace(t, max(2, self.sectors)))
            return colours, ones, colours

        if mode == "wave":
            t = self._along(self.heading) / self.wavelength - phase
            colours = self._palette(t)
            return colours, self._trough(t), colours

        if mode == "ripple":
            t = self._radii / self.wavelength - phase
            colours = self._palette(t)
            return colours, self._trough(t), colours

        if mode == "sweep":
            pos = self._along((self.heading + self._heading_offset) % 360.0)
            width = max(self.MIN_SOFTNESS, 0.5 * self.softness)
            front = -width + self._stepper.progress(now) * (1.0 + 2.0 * width)
            blend = np.clip((front - pos) / width, 0.0, 1.0)
            old = self._palette_one(self._sweep_old)
            new = self._palette_one(self._sweep_new)
            colours = old * (1.0 - blend)[:, None] + new * blend[:, None]
            return colours, ones, colours

        if mode == "halves":
            if self.heading_step > 0:
                heading = self.heading + self._heading_offset
            else:
                heading = self.heading + 360.0 * phase
            p = project(self._plane_positions, heading % 360.0)
            p = np.where(np.abs(p) < 1e-9, 1e-9, p)
            span = max(1e-9, float(np.abs(p).max()) * 2.0)
            width = max(1e-9, self.softness * span)
            side = np.clip(0.5 + p / width, 0.0, 1.0)
            colours = self._palette(self._point + 0.5 * (1.0 - side))
            return colours, ones, colours

        field = self._palette(self._turn_angles())

        if mode == "corners":
            envelope = self._hold_then_fade(self._stepper.progress(now))
            lit = np.where(self._channels == self._channel, envelope, 0.0)
            colours = np.tile(self._palette_one(self._point), (n, 1))
            return colours, lit, field

        if mode == "scatter":
            if len(self._cluster_centres) == 0:
                return field, np.zeros(n), field
            distance = np.linalg.norm(
                self._space[:, None, :] - self._cluster_centres[None, :, :],
                axis=2,
            )
            radius = max(1e-6, self.radius)
            falloff = np.where(
                distance < radius,
                0.5 + 0.5 * np.cos(np.pi * distance / radius),
                0.0,
            )
            best = np.argmax(falloff, axis=1)
            strength = falloff[np.arange(n), best]
            envelope = self._hold_then_fade(self._stepper.progress(now))
            colours = self._palette(self._cluster_points[best])
            return colours, strength * envelope, field

        # noise
        values = self._noise_values()
        if self.sectors > 1:
            values = np.clip(self._terrace(values, self.sectors), 0.0, 1.0)
        colours = self._palette(values)
        return colours, ones, colours

    # --------------------------------------------------------------- render

    def render(self):
        now = self.now
        dt = min(0.5, max(0.0, now - self._last_time))
        self._last_time = now
        if self._drop_pending:
            self._drop_pending = False
            if self.mode_config == "auto" and self.auto_sections:
                self._switch_auto("loud")
        if self._stepper.poll(now):
            self._step(now)
        self._advance(dt)

        colours, lit, field = self._field(now)
        lit = np.clip(np.nan_to_num(np.asarray(lit, dtype=float)), 0.0, 1.0)
        level = self._band.scale(self.reactive_depth)
        strength = self._limiter.apply(lit * level, now)
        dim = self.background * level * (1.0 - lit)
        out = colours * strength[:, None] + field * dim[:, None]
        out = np.clip(np.nan_to_num(out), 0.0, 255.0)
        self.pixels[:] = out[self._zone_of_pixel]
