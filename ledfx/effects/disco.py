"""Disco: sound to light for a room of smart bulbs, hueDynamic style."""

import re
import timeit
from collections import deque
from typing import ClassVar

import numpy as np
import voluptuous as vol

from ledfx.color import parse_color, validate_color
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.utils.band_level import band_masks, frequency_key
from ledfx.effects.utils.layout import zone_map

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
      lamps. When a band peaks its lamps flash with a new palette colour
      and fade down towards the fade brightness until the next beat.
    - Peak: a single channel on the overall loudness. Every hit flashes one
      random lamp (or all of them with link_lights).
    - Void: no hits at all. The palette position follows the loudest
      part of the spectrum, brightness follows the loudness relative to
      the recent average, and quiet passages go pale. Named after the
      film whose colour trips it was tuned to feel like.

    A channel hit is detected the way DJ apps have done it for twenty
    years: the band energy is compared with its own running average and a
    hit needs to beat that average by a good margin, be louder than the
    previous hit as that fades away, and not follow the last hit too
    closely. After two seconds without a hit the lamps drift to random
    colours at the idle brightness so the room never goes dark between
    songs.
    """

    NAME = "Disco"
    CATEGORY = "Classic"
    HIDDEN_KEYS: ClassVar[list[str]] = ["gradient_roll"]
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
        "gate_decay",
        "pulse_block",
    ]

    MODES: ClassVar[list[str]] = ["Spectrum", "Peak", "Void"]
    ASSIGNMENTS: ClassVar[list[str]] = ["Interleaved", "Blocks", "All lights"]
    CHANNEL_COLORS: ClassVar[list[str]] = ["Palette thirds", "Whole palette"]
    STYLES: ClassVar[list[str]] = ["Fade + pulse", "Fade", "Hold"]

    # With at most this many pixels every pixel is treated as its own lamp
    AUTO_ZONE_PIXEL_LIMIT = 32
    AUTO_ZONE_COUNT = 8
    # Minimum distance along the palette between a channel's old and new
    # colour, so every hit is a visible change
    MIN_PALETTE_STEP = 0.15

    # Frames of band energy the running average spans
    HISTORY = 80
    # A hit needs this many times the running average at sensitivity 0.5
    HIT_RATIO = 1.5
    # Corrected energy below this never triggers, keeps noise floors quiet
    HIT_FLOOR = 0.05
    # Shortest time between two hits on one channel
    HIT_MIN_GAP = 0.1
    # A fade lasts as long as the gap since the previous hit, up to this
    FADE_CAP = 1.4
    # Length of a fast pulse
    PULSE_FADE = 0.2
    # Hits per block when fast pulse alternates between pulses and fades
    PEAK_PULSE_BLOCK = 16
    # Seconds without a hit before a channel's lamps start to drift
    IDLE_TIMEOUT = 2.0
    # Time between idle colour changes, and the length of each transition
    IDLE_RAMP = 2.0
    # How long a strobe flash stays on, and the most flashes per second
    STROBE_ON = 0.1
    STROBE_MAX_RATE = 5
    # The Void analyser looks for the loudest bin below this frequency
    VOID_MAX_HZ = 2000
    # How many lamps one Spectrum hit may flash, shared between channels
    SPECTRUM_BATCH = 10

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "mode",
                description="Spectrum: bass, voice and treble lamps. Peak: one lamp per beat on the overall loudness. Void: colour and brightness follow the music continuously",
                default="Spectrum",
            ): vol.In(MODES),
            vol.Optional(
                "sensitivity",
                description="How easily the lights react",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "smoothness",
                description="Lengthens (above 0.5) or shortens (below 0.5) every fade by up to half a second. Void: how much the colour and brightness are averaged",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "intensity",
                description="Overall brightness of the show",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "bass_style",
                description="Bass lamps after a hit: fade to the fade brightness until the next beat, alternate blocks of fades and short pulses, or hold full brightness",
                default="Fade + pulse",
            ): vol.In(STYLES),
            vol.Optional(
                "voice_style",
                description="Voice lamps after a hit",
                default="Hold",
            ): vol.In(STYLES),
            vol.Optional(
                "treble_style",
                description="Treble lamps after a hit",
                default="Fade",
            ): vol.In(STYLES),
            vol.Optional(
                "fade",
                description="Peak mode: a hit fades down to the fade brightness until the next beat. Off holds full brightness until the next hit",
                default=True,
            ): bool,
            vol.Optional(
                "fast_pulse",
                description="Peak mode: alternate blocks of hits between beat length fades and short 200 ms pulses",
                default=True,
            ): bool,
            vol.Optional(
                "fade_brightness",
                description="Brightness a hit fades down to. 0.16 is the app's Normal mood, 0.69 its Relax mood",
                default=0.16,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "idle_brightness",
                description="Brightness the lamps drift to, with slowly changing colours, after two seconds without a hit",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "strobe",
                description="Peak: hits are a strobe flash followed by dark. Spectrum: a bass and treble hit together flashes every lamp with the strobe colour",
                default=False,
            ): bool,
            vol.Optional(
                "link_lights",
                description="Peak mode: flash every lamp on each hit instead of one random lamp",
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
                description="How lamps are shared between the channels: alternating, in blocks along the light order, or every lamp flashes on every channel",
                default="Interleaved",
            ): vol.In(ASSIGNMENTS),
            vol.Optional(
                "channel_colors",
                description="Spectrum mode: bass, voice and treble each keep to their third of the palette, or all three roam the whole palette",
                default="Palette thirds",
            ): vol.In(CHANNEL_COLORS),
            vol.Optional(
                "modulate_saturation",
                description="Void mode: quiet passages go pale, loud ones vivid",
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
            vol.Optional(
                "gate_decay",
                description="Seconds after a hit before a quieter hit can follow it. Longer calms busy music down",
                default=0.9,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.2, max=5.0)),
            vol.Optional(
                "pulse_block",
                description="Hits per block when a channel alternates between fades and pulses",
                default=8,
            ): vol.All(vol.Coerce(int), vol.Range(min=2, max=32)),
        }
    )

    # ---------------------------------------------------------- lifecycle

    def on_activate(self, pixel_count):
        now = timeit.default_timer()
        self._rng = np.random.default_rng()
        self._band_masks = None
        self._band_freq_key = None
        self._last_frame_time = now

        # Per channel detector state. The history starts at full scale so
        # nothing triggers until it holds real music.
        self._history = np.ones((3, self.HISTORY))
        self._hist_idx = 0
        self._gate = np.zeros(3)
        self._last_hit_power = np.zeros(3)
        # Activation counts as the last hit so the idle drift starts two
        # seconds in rather than immediately
        self._hit_time = np.full(3, now)
        self._prev_hit_time = np.full(3, -np.inf)
        self._hit_count = np.zeros(3, dtype=int)
        self._pulse_block = np.zeros(3, dtype=bool)
        self._points = np.array(
            [self._next_point(self._rng.random(), channel) for channel in range(3)]
        )
        self._colors = self._palette(self._points)
        self._last_strobe = -np.inf

        # Void analyser state
        self._rms_history = np.ones(self.HISTORY)
        self._void_pos_ring = deque(maxlen=self._median_len)
        self._void_amp_ring = deque(maxlen=self._average_len)
        self._void_pos = 0.5
        self._void_amp = 0.0

        self._build_zones(pixel_count)
        self._assign_lamps()
        self._reset_lamps()

    def config_updated(self, config):
        self.mode = self._config["mode"]
        self.sensitivity = self._config["sensitivity"]
        self.smoothness = self._config["smoothness"]
        self.intensity = self._config["intensity"]
        self.fade = self._config["fade"]
        self.fast_pulse = self._config["fast_pulse"]
        self.gate_decay = self._config["gate_decay"]
        self.pulse_block = self._config["pulse_block"]
        styles = [
            self._config["bass_style"],
            self._config["voice_style"],
            self._config["treble_style"],
        ]
        if self.mode == "Peak":
            peak = (
                "Hold"
                if not self.fade
                else ("Fade + pulse" if self.fast_pulse else "Fade")
            )
            styles = [peak, peak, peak]
        self.channel_fades = np.array([style != "Hold" for style in styles])
        self.channel_pulses = np.array([style == "Fade + pulse" for style in styles])
        self.fade_brightness = self._config["fade_brightness"]
        self.idle_brightness = self._config["idle_brightness"]
        self.strobe = self._config["strobe"]
        self.link_lights = self._config["link_lights"]
        self.modulate_saturation = self._config["modulate_saturation"]
        self.strobe_color = np.array(
            parse_color(self._config["strobe_color"]), dtype=float
        )
        # Sensitivity is a gain on the band energy, 0.4x to 1.6x, so at 0.5
        # a hit needs HIT_RATIO times the running average
        self.gain = 0.4 + 1.2 * self.sensitivity
        # Smoothness adds up to half a second to, or takes it from, a fade
        self.fade_offset = (self.smoothness - 0.5) * 1.0
        # Void ring buffers: 2 to 5 frames of amplitude, three times
        # that of colour position
        self._average_len = 2 + round(3 * self.smoothness)
        self._median_len = 3 * self._average_len
        self.palette_thirds = (
            self.mode == "Spectrum"
            and self._config["channel_colors"] == "Palette thirds"
        )
        self._band_masks = None
        self.enabled = np.array(
            [self._config[name] for name in CHANNEL_NAMES], dtype=bool
        )
        if self.mode == "Peak":
            # Peak listens to the overall loudness on channel 0 only
            self.enabled = np.array([True, False, False])
        if getattr(self, "pixels", None) is not None:
            self._build_zones(self.pixel_count)
            self._assign_lamps()
            if len(self._lamp_hit) != self._zone_count:
                self._reset_lamps()
            self._void_pos_ring = deque(self._void_pos_ring, maxlen=self._median_len)
            self._void_amp_ring = deque(self._void_amp_ring, maxlen=self._average_len)

    # ---------------------------------------------------------------- lamps

    def _build_zones(self, pixel_count):
        self._zone_count, self._zone_of_pixel = zone_map(
            pixel_count,
            self._config["zones"],
            self.AUTO_ZONE_PIXEL_LIMIT,
            self.AUTO_ZONE_COUNT,
        )

    def _reset_lamps(self):
        n = self._zone_count
        self._lamp_color = np.zeros((n, 3))
        self._lamp_hit = np.full(n, -np.inf)
        self._lamp_fade = np.full(n, np.inf)
        self._lamp_strobe_until = np.full(n, -np.inf)
        self._lamp_dark_after = np.zeros(n, dtype=bool)
        # Until a lamp is hit its idle drift follows its own channel
        self._lamp_channel_hit = np.where(
            self._lamp_channel >= 0, self._lamp_channel, 0
        )
        self._lamp_idle_tick = np.full(n, -1)
        self._lamp_idle_from = np.zeros((n, 3))
        self._lamp_idle_target = np.zeros((n, 3))
        self._lamp_out = np.zeros((n, 3))

    def _assign_lamps(self):
        """
        Work out which channel every lamp listens to.

        Sets self._lamp_channel, an int array with the channel index per
        lamp, -1 for a lamp that is off and -2 for a lamp that flashes on
        every channel.
        """
        n = self._zone_count
        channels = [i for i in range(3) if self.enabled[i]]
        lamp_channel = np.full(n, -1, dtype=int)

        light_map = self._config["light_map"]
        if self.mode == "Peak":
            lamp_channel[:] = 0
        elif light_map:
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

    def _channel_lamps(self, channel):
        """Indices of the lamps that flash on a hit of this channel."""
        return np.flatnonzero(
            (self._lamp_channel == channel) | (self._lamp_channel == -2)
        )

    def _palette(self, points):
        return self.get_gradient_color_vectorized1d(
            np.asarray(points, dtype=float) % 1.0
        )

    def _next_point(self, point, channel):
        """
        A new palette position for a channel, clearly away from the old one.

        With palette thirds, bass keeps to the first third of the palette,
        voice to the middle and treble to the last third.
        """
        shift = self._rng.uniform(self.MIN_PALETTE_STEP, 1.0 - self.MIN_PALETTE_STEP)
        if not self.palette_thirds:
            return (point + shift) % 1.0
        start = channel / 3.0
        return start + ((point - start + shift / 3.0) % (1.0 / 3.0))

    def _new_channel_color(self, channel):
        self._points[channel] = self._next_point(self._points[channel], channel)
        self._colors[channel] = self._palette([self._points[channel]])[0]
        return self._colors[channel]

    # ---------------------------------------------------------------- audio

    def _band_edges(self):
        return [
            (self._config["bass_low"], self._config["bass_high"]),
            (self._config["voice_low"], self._config["voice_high"]),
            (self._config["treble_low"], self._config["treble_high"]),
            (0, self.VOID_MAX_HZ),
        ]

    def _masks_for(self, frequencies):
        """Boolean melbank masks for the bands, cached per frequency axis."""
        key = frequency_key(frequencies)
        if self._band_masks is None or self._band_freq_key != key:
            self._band_masks = band_masks(frequencies, self._band_edges())
            self._band_freq_key = key
        return self._band_masks

    @staticmethod
    def band_powers(melbank, masks):
        """Mean melbank power in each band."""
        melbank = np.asarray(melbank, dtype=float)
        return np.array([float(np.mean(melbank[mask])) for mask in masks], dtype=float)

    def _detect(self, channel, power, now, dt):
        """Run the hit detector of one channel on this frame's band power."""
        history = self._history[channel]
        average = float(history.mean())
        history[self._hist_idx] = power

        # The gate left by the previous hit falls linearly to zero
        self._gate[channel] = max(
            0.0,
            self._gate[channel] - self._last_hit_power[channel] * dt / self.gate_decay,
        )
        corrected = power * self.gain
        triggered = (
            corrected > self.HIT_FLOOR
            and corrected > self.HIT_RATIO * average
            and power > self._gate[channel]
            and now - self._hit_time[channel] > self.HIT_MIN_GAP
        )
        if triggered:
            self._gate[channel] = power
            self._last_hit_power[channel] = power
        return triggered

    def _fade_for(self, channel, now, block):
        """
        Fade length of a hit: the gap since the previous hit, or a pulse.

        Channels that hold return infinity. A channel that pulses swaps
        between blocks of beat length fades and blocks of short pulses.
        """
        previous = self._prev_hit_time[channel]
        interval = now - previous if np.isfinite(previous) else self.FADE_CAP
        interval = min(self.FADE_CAP, interval)

        self._hit_count[channel] += 1
        if self._hit_count[channel] >= block:
            self._hit_count[channel] = 0
            self._pulse_block[channel] = (
                self.channel_pulses[channel] and not self._pulse_block[channel]
            )

        if not self.channel_fades[channel]:
            return np.inf
        fade = self.PULSE_FADE if self._pulse_block[channel] else interval
        return max(0.05, fade + self.fade_offset)

    def _flash(self, lamps, channel, color, now, fade):
        """Light lamps with a colour that fades over `fade` seconds."""
        if len(lamps) == 0:
            return
        self._lamp_color[lamps] = color
        self._lamp_hit[lamps] = now
        self._lamp_fade[lamps] = fade
        self._lamp_strobe_until[lamps] = -np.inf
        self._lamp_dark_after[lamps] = False
        self._lamp_channel_hit[lamps] = channel
        self._lamp_idle_tick[lamps] = -1

    def _hit_spectrum(self, channel, now):
        lamps = self._channel_lamps(channel)
        if self._config["assignment"] != "All lights":
            enabled = max(1, int(self.enabled.sum()))
            batch = max(1, self.SPECTRUM_BATCH // enabled)
            if len(lamps) > batch:
                lamps = self._rng.choice(lamps, size=batch, replace=False)
        fade = self._fade_for(channel, now, self.pulse_block)
        color = self._new_channel_color(channel)
        self._flash(lamps, channel, color, now, fade)
        self._prev_hit_time[channel] = now
        self._hit_time[channel] = now

    def _hit_peak(self, now):
        n = self._zone_count
        if self.strobe and now - self._last_strobe < 1.0 / self.STROBE_MAX_RATE:
            # Too soon after the last flash: this hit is dropped before it
            # advances the pulse block bookkeeping
            return
        if self.link_lights:
            lamps = np.arange(n)
        else:
            lamps = np.array([int(self._rng.integers(n))])
        fade = self._fade_for(0, now, self.PEAK_PULSE_BLOCK)
        if self.strobe:
            self._last_strobe = now
            self._lamp_strobe_until[lamps] = now + self.STROBE_ON
            self._lamp_dark_after[lamps] = True
            self._lamp_hit[lamps] = now
            self._lamp_channel_hit[lamps] = 0
            self._lamp_idle_tick[lamps] = -1
        else:
            self._flash(lamps, 0, self._new_channel_color(0), now, fade)
        self._prev_hit_time[0] = now
        self._hit_time[0] = now

    def _strobe_spectrum(self, now):
        """Bass and treble together: every lamp flashes the strobe colour."""
        if now - self._last_strobe < 1.0 / self.STROBE_MAX_RATE:
            return
        self._last_strobe = now
        lamps = np.flatnonzero(self._lamp_channel != -1)
        fade = max(0.05, self.PULSE_FADE + self.fade_offset)
        for channel in range(3):
            self._hit_time[channel] = now
        self._flash(lamps, 0, self.strobe_color, now, fade)

    def _analyse_void(self, melbank, masks, now):
        band = melbank[masks[3]]
        if len(band) > 1:
            position = float(np.argmax(band)) / (len(band) - 1)
        else:
            position = 0.5
        self._void_pos_ring.append(position)
        self._void_pos = float(np.median(self._void_pos_ring))

        loudness = float(np.mean(melbank))
        average = float(self._rms_history.mean())
        self._rms_history[self._hist_idx] = loudness
        corrected = loudness * self.gain
        if corrected < self.HIT_FLOOR or average <= 0:
            amplitude = 0.0
        else:
            amplitude = corrected / (average * self.HIT_RATIO)
        self._void_amp_ring.append(min(1.0, amplitude))
        self._void_amp = float(np.mean(self._void_amp_ring))

    def analyse(self, melbank, frequencies, now):
        """
        Feed one melbank frame. Returns the channels that hit on this frame.

        Split out from audio_data_updated so it can be driven directly.
        """
        melbank = np.nan_to_num(np.asarray(melbank, dtype=float))
        masks = self._masks_for(frequencies)
        dt = min(0.1, max(0.0, now - self._last_frame_time))
        self._last_frame_time = now
        hits = np.zeros(3, dtype=bool)

        if self.mode == "Void":
            self._analyse_void(melbank, masks, now)
        elif self.mode == "Peak":
            loudness = float(np.mean(melbank))
            if self._detect(0, loudness, now, dt):
                hits[0] = True
                self._hit_peak(now)
        else:
            powers = self.band_powers(melbank, masks[:3])
            for channel in np.flatnonzero(self.enabled):
                if self._detect(channel, powers[channel], now, dt):
                    hits[channel] = True
            for channel in np.flatnonzero(hits):
                self._hit_spectrum(channel, now)
            if self.strobe and hits[0] and hits[2]:
                self._strobe_spectrum(now)

        self._hist_idx = (self._hist_idx + 1) % self.HISTORY
        return hits

    def audio_data_updated(self, data):
        melbanks = data.melbanks
        # The last melbank spans the whole audible range
        melbank = melbanks.melbanks[-1]
        frequencies = melbanks.melbank_processors[-1].melbank_frequencies
        self.analyse(melbank, frequencies, timeit.default_timer())

    # --------------------------------------------------------------- render

    def _lamp_levels(self, now):
        """Brightness 0..1 of every lamp from its last hit."""
        elapsed = now - self._lamp_hit
        hit = np.isfinite(self._lamp_hit)
        fade = self._lamp_fade
        with np.errstate(invalid="ignore", divide="ignore"):
            progress = np.where(np.isfinite(fade), elapsed / fade, 0.0)
        progress = np.clip(np.nan_to_num(progress), 0.0, 1.0)
        levels = 1.0 - (1.0 - self.fade_brightness) * progress
        levels = np.where(hit, levels, 0.0)
        levels = np.where(self._lamp_dark_after, 0.0, levels)
        return levels

    def _idle(self, out, now):
        """Drift idle lamps to random colours at the idle brightness."""
        idle_channels = (now - self._hit_time) > self.IDLE_TIMEOUT
        channels = self._lamp_channel_hit
        lamp_idle = idle_channels[channels] & (self._lamp_channel != -1)
        if not lamp_idle.any():
            return out

        idle_start = self._hit_time[channels] + self.IDLE_TIMEOUT
        ticks = np.floor((now - idle_start) / self.IDLE_RAMP).astype(int)
        fresh = lamp_idle & (ticks != self._lamp_idle_tick)
        for lamp in np.flatnonzero(fresh):
            self._lamp_idle_tick[lamp] = ticks[lamp]
            self._lamp_idle_from[lamp] = self._lamp_out[lamp]
            channel = int(channels[lamp])
            point = self._next_point(self._rng.random(), channel)
            self._lamp_idle_target[lamp] = (
                self._palette([point])[0] * self.idle_brightness
            )

        t = np.clip(
            (now - (idle_start + ticks * self.IDLE_RAMP)) / self.IDLE_RAMP,
            0.0,
            1.0,
        )[:, None]
        drift = (
            self._lamp_idle_from + (self._lamp_idle_target - self._lamp_idle_from) * t
        )
        return np.where(lamp_idle[:, None], drift, out)

    def _render_hits(self, now):
        levels = self._lamp_levels(now)
        out = self._lamp_color * levels[:, None]
        strobing = now < self._lamp_strobe_until
        out[strobing] = self.strobe_color
        out = self._idle(out, now)
        self._lamp_out = out
        return out

    def _render_void(self):
        """Void: colour from the loudest band, brightness from the loudness."""
        color = self._palette([self._void_pos])[0]
        brightness = float(np.clip(self._void_amp, 0.0, 1.0))
        saturation = brightness if self.modulate_saturation else 1.0
        color = 255.0 * (1.0 - saturation) + color * saturation
        out = np.tile(color * brightness, (self._zone_count, 1))
        self._lamp_out = out
        return out

    def render(self):
        if self.mode == "Void":
            lamp_pixels = self._render_void()
        else:
            lamp_pixels = self._render_hits(self.now)
        self.pixels[:] = lamp_pixels[self._zone_of_pixel] * self.intensity
