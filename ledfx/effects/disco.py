"""Disco: sound to light for a room of smart bulbs, hueDynamic style."""

import re
import timeit

import numpy as np
import voluptuous as vol

from ledfx.color import parse_color, validate_color
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.math import ExpFilter

# Channel letters accepted by light_map, in channel index order
CHANNEL_LETTERS = "BVT"
CHANNEL_NAMES = ["bass", "voice", "treble"]


def validate_light_map(value):
    value = str(value).upper().replace(" ", "")
    if not re.fullmatch(r"[BVT\-]*", value):
        raise vol.Invalid(
            "Light map may only contain B, V, T and - (one letter per lamp)"
        )
    return value


class DiscoEffect(AudioReactiveEffect, GradientEffect):
    """
    Sound to light in the style of the "Disco" modes of Hue apps such as
    hueDynamic, for setups where every pixel is a whole lamp.

    Three analysers:

    - Spectrum: three channels, bass, voice and treble, each listening to
      its own frequency band. Every channel is assigned to some of the
      lamps. When a band peaks its lamps flash with a new palette colour.
    - Peak: a single channel on the beat. All lamps pulse together with a
      new colour on every hit, optionally with a strobe flash and an idle
      glow between hits.
    - Neural: no hits at all. The palette position follows where the
      energy sits in the spectrum (low end of the palette for bass heavy
      passages, high end for bright ones), brightness follows loudness and
      transients wash the colour towards white.

    Sensitivity sets how easily a channel triggers, smoothness how
    sluggish it is, intensity how hard the lamps react.
    """

    NAME = "Disco"
    CATEGORY = "Classic"
    HIDDEN_KEYS = ["gradient_roll"]
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "zones",
        "light_map",
        "bass_low",
        "bass_high",
        "voice_low",
        "voice_high",
        "treble_low",
        "treble_high",
        "strobe_color",
    ]

    MODES = ["Spectrum", "Peak", "Neural"]
    ASSIGNMENTS = ["Interleaved", "Blocks", "All lights"]

    # With at most this many pixels every pixel is treated as its own lamp
    AUTO_ZONE_PIXEL_LIMIT = 32
    AUTO_ZONE_COUNT = 8
    # Minimum distance along the palette between a lamp's old and new colour
    MIN_PALETTE_STEP = 0.15
    # A channel needs at least this much power to trigger, whatever the
    # running average says
    HIT_FLOOR = 0.12
    # Shortest time between two hits on one channel, keeps the bulbs from
    # being asked for more than they can show
    HIT_MIN_GAP = 0.12
    # Pulse decay time constants in seconds
    FAST_PULSE_TAU = 0.12
    SLOW_PULSE_TAU = 0.4
    # How long the strobe colour is shown at the start of a hit
    STROBE_TIME = 0.06
    # Spread of palette positions across the lamps in Neural mode
    NEURAL_SPREAD = 0.2

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "mode",
                description="Spectrum: bass, voice and treble lamps. Peak: all lamps on the beat. Neural: colour and brightness follow the music continuously",
                default="Spectrum",
            ): vol.In(MODES),
            vol.Optional(
                "sensitivity",
                description="How easily the lights react",
                default=0.6,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "smoothness",
                description="How sluggish the lights are. Higher smooths out fast changes",
                default=0.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "intensity",
                description="How hard the lamps react, from a gentle pulse to full flashes",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "idle_brightness",
                description="Brightness of the lamps between hits",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "fade",
                description="Pulse fades out after a hit. Off makes the lamps follow the loudness of their band instead",
                default=True,
            ): bool,
            vol.Optional(
                "fast_pulse",
                description="Short, sharp pulses instead of a slow decay",
                default=True,
            ): bool,
            vol.Optional(
                "strobe",
                description="Flash the strobe colour at the start of every hit (Peak mode)",
                default=False,
            ): bool,
            vol.Optional(
                "bass",
                description="Enable the bass channel",
                default=True,
            ): bool,
            vol.Optional(
                "voice",
                description="Enable the voice channel",
                default=True,
            ): bool,
            vol.Optional(
                "treble",
                description="Enable the treble channel",
                default=True,
            ): bool,
            vol.Optional(
                "assignment",
                description="How lamps are shared between the channels: alternating, in blocks along the light order, or every lamp shows the loudest channel",
                default="Interleaved",
            ): vol.In(ASSIGNMENTS),
            vol.Optional(
                "modulate_saturation",
                description="Neural mode: transients wash the colour towards white",
                default=True,
            ): bool,
            vol.Optional(
                "light_map",
                description="Channel per lamp, e.g. BVTBV. B bass, V voice, T treble, - off. Overrides the assignment",
                default="",
            ): validate_light_map,
            vol.Optional(
                "zones",
                description="Number of lamps / zones to split the output into. 0 = auto (one per pixel for bulbs)",
                default=0,
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=64)),
            vol.Optional(
                "bass_low", description="Bass band low edge in Hz", default=40
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=15000)),
            vol.Optional(
                "bass_high",
                description="Bass band high edge in Hz",
                default=180,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=15000)),
            vol.Optional(
                "voice_low",
                description="Voice band low edge in Hz",
                default=220,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=15000)),
            vol.Optional(
                "voice_high",
                description="Voice band high edge in Hz",
                default=2000,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=15000)),
            vol.Optional(
                "treble_low",
                description="Treble band low edge in Hz",
                default=3000,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=15000)),
            vol.Optional(
                "treble_high",
                description="Treble band high edge in Hz",
                default=12000,
            ): vol.All(vol.Coerce(int), vol.Range(min=20, max=15000)),
            vol.Optional(
                "strobe_color",
                description="Colour of the strobe flash",
                default="#FFFFFF",
            ): validate_color,
        }
    )

    def on_activate(self, pixel_count):
        now = timeit.default_timer()
        self._rng = np.random.default_rng()
        self._band_masks = None
        self._band_freq_count = 0
        # Per channel state: bass, voice, treble
        self._power = np.zeros(3)
        self._average = np.zeros(3)
        self._follow = np.zeros(3)
        self._hit_time = np.full(3, -np.inf)
        self._points = self._rng.random(3)
        self._colors = self._palette(self._points)
        # Neural state
        self._loudness = 0.0
        self._loudness_slow = 0.0
        self._centroid = 0.5
        self._build_zones(pixel_count)
        self._assign_lamps()

    def config_updated(self, config):
        self.mode = self._config["mode"]
        self.sensitivity = self._config["sensitivity"]
        self.smoothness = self._config["smoothness"]
        self.intensity = self._config["intensity"]
        self.idle = self._config["idle_brightness"]
        self.fade = self._config["fade"]
        self.fast_pulse = self._config["fast_pulse"]
        self.strobe = self._config["strobe"]
        self.modulate_saturation = self._config["modulate_saturation"]
        self.strobe_color = np.array(
            parse_color(self._config["strobe_color"]), dtype=float
        )
        # Audio gain: 0.5x at zero sensitivity up to 3.5x at full
        self.gain = 0.5 + 3.0 * self.sensitivity
        # A hit needs the band to jump this far above its running average
        self.hit_ratio = 1.15 + 1.0 * (1.0 - self.sensitivity)
        self.pulse_tau = (
            self.FAST_PULSE_TAU if self.fast_pulse else self.SLOW_PULSE_TAU
        ) * (1.0 + 3.0 * self.smoothness)
        # Smoothing of the band power the detectors and followers see
        alpha = 0.95 - 0.85 * self.smoothness
        self._power_filter = ExpFilter(
            np.zeros(3), alpha_decay=alpha * 0.5, alpha_rise=alpha
        )
        self._average_filter = ExpFilter(
            np.zeros(3), alpha_decay=0.02, alpha_rise=0.02
        )
        self._loudness_filter = ExpFilter(
            0.0, alpha_decay=alpha * 0.3, alpha_rise=alpha
        )
        self._loudness_slow_filter = ExpFilter(
            0.0, alpha_decay=0.05, alpha_rise=0.05
        )
        self._centroid_filter = ExpFilter(
            0.5, alpha_decay=alpha * 0.3, alpha_rise=alpha * 0.3
        )
        self._band_masks = None
        self.enabled = np.array(
            [self._config[name] for name in CHANNEL_NAMES], dtype=bool
        )
        if self.mode == "Peak":
            # Peak listens to the bass band only, whatever the channel
            # toggles say
            self.enabled = np.array([True, False, False])
        if getattr(self, "pixels", None) is not None:
            self._build_zones(self.pixel_count)
            self._assign_lamps()

    # ---------------------------------------------------------------- lamps

    def _build_zones(self, pixel_count):
        zones = self._config["zones"]
        if zones <= 0:
            if pixel_count <= self.AUTO_ZONE_PIXEL_LIMIT:
                zones = pixel_count
            else:
                zones = self.AUTO_ZONE_COUNT
        zones = max(1, min(zones, pixel_count))
        self._zone_count = zones
        self._zone_of_pixel = (np.arange(pixel_count) * zones) // pixel_count

    def _assign_lamps(self):
        """
        Work out which channel every lamp listens to.

        Sets self._lamp_channel, an int array with the channel index per
        lamp, -1 for a lamp that is off and -2 for a lamp that shows
        whichever channel is loudest.
        """
        n = self._zone_count
        channels = [i for i in range(3) if self.enabled[i]]
        lamp_channel = np.full(n, -1, dtype=int)

        light_map = self._config["light_map"]
        if light_map:
            for lamp in range(n):
                letter = light_map[lamp % len(light_map)]
                if letter in CHANNEL_LETTERS:
                    channel = CHANNEL_LETTERS.index(letter)
                    if self.enabled[channel]:
                        lamp_channel[lamp] = channel
        elif channels:
            assignment = self._config["assignment"]
            if assignment == "All lights":
                lamp_channel[:] = -2
            elif assignment == "Blocks":
                for lamp in range(n):
                    lamp_channel[lamp] = channels[lamp * len(channels) // n]
            else:
                for lamp in range(n):
                    lamp_channel[lamp] = channels[lamp % len(channels)]

        self._lamp_channel = lamp_channel

    def _palette(self, points):
        return self.get_gradient_color_vectorized1d(
            np.asarray(points, dtype=float) % 1.0
        )

    def _next_point(self, point):
        shift = self._rng.uniform(
            self.MIN_PALETTE_STEP, 1.0 - self.MIN_PALETTE_STEP
        )
        return (point + shift) % 1.0

    # ---------------------------------------------------------------- audio

    def _band_edges(self):
        return [
            (self._config["bass_low"], self._config["bass_high"]),
            (self._config["voice_low"], self._config["voice_high"]),
            (self._config["treble_low"], self._config["treble_high"]),
        ]

    def _masks_for(self, frequencies):
        """Boolean melbank masks for the three bands, cached per axis."""
        frequencies = np.asarray(frequencies)
        if self._band_masks is None or self._band_freq_count != len(
            frequencies
        ):
            masks = []
            for low, high in self._band_edges():
                low, high = min(low, high), max(low, high)
                mask = (frequencies >= low) & (frequencies <= high)
                if not mask.any():
                    # Band narrower than the melbank resolution, take the
                    # nearest bin so the channel still does something
                    mask[np.argmin(np.abs(frequencies - (low + high) / 2))] = (
                        True
                    )
                masks.append(mask)
            self._band_masks = masks
            self._band_freq_count = len(frequencies)
        return self._band_masks

    @staticmethod
    def band_powers(melbank, masks):
        """Mean melbank power in each band."""
        melbank = np.asarray(melbank, dtype=float)
        return np.array(
            [float(np.mean(melbank[mask])) for mask in masks], dtype=float
        )

    def analyse(self, melbank, frequencies, now):
        """
        Feed one melbank frame. Returns the channels that hit on this frame.

        Split out from audio_data_updated so it can be driven directly.
        """
        melbank = np.nan_to_num(np.asarray(melbank, dtype=float))
        masks = self._masks_for(frequencies)

        raw = np.minimum(1.0, self.band_powers(melbank, masks) * self.gain)
        self._power = self._power_filter.update(raw)
        self._average = self._average_filter.update(self._power)

        threshold = np.maximum(self.HIT_FLOOR, self._average * self.hit_ratio)
        hits = (self._power >= threshold) & (
            now - self._hit_time > self.HIT_MIN_GAP
        )
        hits &= self.enabled
        for channel in np.flatnonzero(hits):
            self._hit_time[channel] = now
            self._points[channel] = self._next_point(self._points[channel])
        if hits.any():
            self._colors = self._palette(self._points)

        # Neural analyser: overall loudness and where the energy sits
        total = float(np.sum(melbank))
        loud = min(1.0, float(np.mean(melbank)) * self.gain * 2.0)
        self._loudness = self._loudness_filter.update(loud)
        self._loudness_slow = self._loudness_slow_filter.update(loud)
        if total > 1e-6:
            centroid = float(
                np.dot(np.linspace(0.0, 1.0, len(melbank)), melbank) / total
            )
            self._centroid = self._centroid_filter.update(centroid)
        return hits

    def audio_data_updated(self, data):
        melbanks = data.melbanks
        # The last melbank spans the whole audible range
        melbank = melbanks.melbanks[-1]
        frequencies = melbanks.melbank_processors[-1].melbank_frequencies
        self.analyse(melbank, frequencies, timeit.default_timer())

    # --------------------------------------------------------------- render

    def _channel_levels(self, now):
        """Brightness 0..1 of each channel right now."""
        if self.fade:
            elapsed = now - self._hit_time
            level = np.exp(-np.maximum(0.0, elapsed) / self.pulse_tau)
        else:
            level = np.clip(self._power, 0.0, 1.0)
        return level * self.enabled

    def _brightness(self, level):
        """Apply intensity and idle brightness to a 0..1 level."""
        return self.idle + (1.0 - self.idle) * self.intensity * level

    def _render_channels(self, now, single_channel):
        """Spectrum and Peak: lamps lit by their channel's hits."""
        levels = self._channel_levels(now)
        colors = self._colors.copy()

        if self.strobe:
            fresh = (now - self._hit_time) < self.STROBE_TIME
            colors[fresh] = self.strobe_color

        n = self._zone_count
        lamp_channel = self._lamp_channel
        if single_channel is not None:
            lamp_channel = np.full(n, single_channel, dtype=int)
        loudest = int(np.argmax(levels))
        lamp_channel = np.where(lamp_channel == -2, loudest, lamp_channel)

        lamp_levels = np.zeros(n)
        lamp_colors = np.zeros((n, 3))
        on = lamp_channel >= 0
        lamp_levels[on] = levels[lamp_channel[on]]
        lamp_colors[on] = colors[lamp_channel[on]]
        return lamp_colors * self._brightness(lamp_levels)[:, None]

    def _render_neural(self):
        """Colour from the spectral balance, brightness from loudness."""
        n = self._zone_count
        offsets = (np.arange(n) / max(1, n - 1) - 0.5) * self.NEURAL_SPREAD
        points = np.clip(self._centroid + offsets, 0.0, 1.0)
        colors = self._palette(points)
        if self.modulate_saturation:
            transient = max(0.0, self._loudness - self._loudness_slow)
            wash = min(1.0, 2.0 * transient)
            colors = colors * (1.0 - wash) + 255.0 * wash
        return colors * self._brightness(self._loudness)

    def render(self):
        now = self.now
        if self.mode == "Neural":
            lamp_pixels = self._render_neural()
        elif self.mode == "Peak":
            lamp_pixels = self._render_channels(now, single_channel=0)
        else:
            lamp_pixels = self._render_channels(now, single_channel=None)
        self.pixels[:] = lamp_pixels[self._zone_of_pixel]
