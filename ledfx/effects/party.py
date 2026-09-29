"""Party: tempo and audio driven effect families for smart bulbs and strips."""

import timeit

import numpy as np
import voluptuous as vol

from ledfx.color import parse_color, validate_color
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.utils.step_trigger import StepTrigger, step_trigger_schema

# Colour envelope shapes for the adsr family. Each channel is
# (attack, hold, decay, sustain, release, peak) as fractions of one event,
# or a single colour with one brightness envelope.
SHAPES = {
    "Single colour": {
        "single": True,
        "brightness": (0.04, 0.08, 0.16, 0.16, 0.62, 1.0),
    },
    "Frost": {
        "red": (0.01, 0.02, 0.08, 0.0, 0.0, 0.85),
        "green": (0.01, 0.02, 0.18, 0.0, 0.0, 1.0),
        "blue": (0.01, 0.02, 0.29, 0.0, 0.0, 1.0),
    },
    "Magenta": {
        "red": (0.12, 0.0, 0.38, 0.0, 0.0, 1.0),
        "green": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        "blue": (0.12, 0.0, 0.58, 0.0, 0.0, 1.0),
    },
    "Coral": {
        "single": True,
        "brightness": (0.01, 0.5, 0.25, 0.25, 0.0, 1.0),
    },
    "Rose": {
        "red": (0.4, 0.05, 0.1, 0.8, 0.45, 0.8),
        "green": (0.4, 0.05, 0.1, 0.12, 0.45, 0.12),
        "blue": (0.2, 0.05, 0.3, 0.35, 0.45, 0.55),
    },
    "Ember": {
        "red": (0.01, 0.03, 0.5, 0.18, 0.46, 1.0),
        "green": (0.01, 0.03, 0.32, 0.0, 0.0, 0.85),
        "blue": (0.01, 0.03, 0.09, 0.0, 0.0, 0.65),
    },
    "Spectrum": {
        "red": (0.02, 0.03, 0.24, 0.045, 0.08, 1.0),
        "green": (0.3, 0.0, 0.32, 0.0, 0.0, 0.8),
        "blue": (0.65, 0.0, 0.25, 0.07, 0.1, 0.6),
    },
    "Prism": {
        "red": (0.04, 0.08, 0.2, 0.0, 0.68, 1.0),
        "green": (0.2, 0.0, 0.4, 0.0, 0.4, 0.8),
        "blue": (0.4, 0.0, 0.0, 0.6, 0.6, 0.6),
    },
}


def curve(progress, kind):
    """Easing curve on a 0..1 progress, vectorised."""
    p = np.clip(progress, 0.0, 1.0)
    if kind == "cut":
        return np.where(p > 0.0, 1.0, 0.0)
    if kind == "ease in":
        return p * p
    if kind == "ease out":
        return 1.0 - (1.0 - p) * (1.0 - p)
    if kind == "ease in out":
        return np.where(
            p < 0.5, 4.0 * p * p * p, 1.0 - ((-2.0 * p + 2.0) ** 3) / 2.0
        )
    return p


def ahdsr(envelope, progress, kind):
    """
    Sample an attack / hold / decay / sustain / release envelope.

    envelope: (attack, hold, decay, sustain, release, peak), the times as
    fractions of the event, the levels 0..1. Returns 0 outside the event.
    """
    attack, hold, decay, sustain, release, peak = envelope
    total = attack + hold + decay + release
    if total > 1.0:
        attack, hold, decay, release = (
            x / total for x in (attack, hold, decay, release)
        )
    sustain = min(peak, sustain)
    p = float(progress)
    if not (0.0 <= p < 1.0):
        return 0.0
    hold_end = attack + hold
    decay_end = hold_end + decay
    release_start = 1.0 - release
    if p < attack:
        return peak * float(curve(p / attack, kind))
    if p < hold_end:
        return peak
    if p < decay_end:
        return peak + (sustain - peak) * float(
            curve((p - hold_end) / decay, kind)
        )
    if p < release_start:
        return sustain
    if release <= 0.0:
        return 0.0
    return sustain * (1.0 - float(curve((p - release_start) / release, kind)))


def hash01(seed, keys, event):
    """Deterministic 0..1 noise per key and event, vectorised over keys."""
    keys = np.asarray(keys, dtype=np.uint64)
    x = (
        (keys * np.uint64(2654435761))
        ^ (np.uint64(event & 0xFFFFFFFF) * np.uint64(2246822519))
        ^ np.uint64(seed)
    )
    x ^= x >> np.uint64(15)
    x *= np.uint64(2246822519)
    x ^= x >> np.uint64(13)
    x *= np.uint64(3266489917)
    x ^= x >> np.uint64(16)
    return (x & np.uint64(0xFFFFFF)).astype(float) / float(0x1000000)


class PartyEffect(AudioReactiveEffect, GradientEffect):
    """
    Effect families of the "Party" show engine in Hue apps such as
    hueDynamic, driven by the beat tracker instead of a fixed BPM.

    Every step (a beat, or a fraction or multiple of one) starts an event.
    Each event plays an envelope, attack / hold / release in beats, and a
    family kernel decides how strongly each lamp takes part in it and which
    palette colour it shows:

    - adsr:     every lamp plays a colour envelope over one step
    - chase:    the envelope runs from lamp to lamp along the light order
    - radial:   a ring that spreads out from an origin
    - wash:     soft colour waves rolling along the lamps
    - scan:     a bright line bouncing back and forth
    - streak:   a comet with a fading trail, only some of the time
    - twinkle:  random lamps light up on every step
    - breathe:  the whole room breathes as one
    - gate:     a wash that opens with the music level
    - burst:    random lamps flash when the band accents

    With reactive depth above zero the brightness follows the level of a
    frequency band, so quiet passages dim the show and accents punch it.
    A flash limiter keeps any lamp from jumping to bright more often than
    about three times a second.
    """

    NAME = "Party"
    CATEGORY = "BPM"
    HIDDEN_KEYS = ["gradient_roll"]
    ADVANCED_KEYS = AudioReactiveEffect.ADVANCED_KEYS + [
        "zones",
        "order",
        "origin",
        "radius",
        "stagger",
        "trail",
        "sensitivity",
        "smoothing",
        "flash_limit",
    ]

    FAMILIES = [
        "adsr",
        "chase",
        "radial",
        "wash",
        "scan",
        "streak",
        "twinkle",
        "breathe",
        "gate",
        "burst",
    ]
    CURVES = ["cut", "linear", "ease in", "ease out", "ease in out"]
    DIRECTIONS = ["forward", "reverse", "alternate", "random"]
    ORDERS = ["Position", "Random"]
    BANDS = ["Full", "Bass", "Mids", "High"]

    AUTO_ZONE_PIXEL_LIMIT = 32
    AUTO_ZONE_COUNT = 8
    # A lamp may not rise to bright again within this many seconds
    FLASH_BRIGHT = 0.55
    FLASH_INTERVAL = 0.35
    # Shortest time between two burst events
    BURST_INTERVAL = 0.4
    # Audio level smoothing in seconds before the smoothing setting scales it
    LEVEL_ATTACK = 0.03
    LEVEL_RELEASE = 0.22
    # Band edges in Hz for the reactive levels
    BAND_EDGES = [(20, 250), (250, 3000), (3000, 9000)]

    CONFIG_SCHEMA = vol.Schema(
        {
            vol.Optional(
                "family",
                description="Which kind of show: adsr colour envelopes, chase, radial ring, wash, scan, streak, twinkle, breathe, volume gate or burst",
                default="chase",
            ): vol.In(FAMILIES),
            vol.Optional(
                "shape",
                description="adsr family: the colour envelope every lamp plays on each step",
                default="Single colour",
            ): vol.In(list(SHAPES.keys())),
            vol.Optional(
                "color",
                description="Colour for the single colour envelope shapes",
                default="#0080FF",
            ): validate_color,
            **step_trigger_schema(
                trigger="Beat", steps_per_beat="1", timer_bpm=120
            ),
            vol.Optional(
                "curve",
                description="Shape of the rises and falls",
                default="ease in out",
            ): vol.In(CURVES),
            vol.Optional(
                "direction",
                description="Which way the movement runs, per event",
                default="forward",
            ): vol.In(DIRECTIONS),
            vol.Optional(
                "attack",
                description="Rise time of each event in beats",
                default=0.125,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=8.0)),
            vol.Optional(
                "hold",
                description="Time each event holds full brightness in beats",
                default=0.25,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=8.0)),
            vol.Optional(
                "release",
                description="Fall time of each event in beats",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=8.0)),
            vol.Optional(
                "stagger",
                description="chase: delay between one lamp and the next in beats",
                default=0.125,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=4.0)),
            vol.Optional(
                "trail",
                description="scan and streak: length of the trail in beats",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=8.0)),
            vol.Optional(
                "probability",
                description="twinkle, streak and burst: chance that a lamp or an event takes part",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "origin",
                description="radial: where along the lamps the ring starts, 0 first lamp, 1 last lamp",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "radius",
                description="radial: how far the ring travels. wash: how wide the waves are",
                default=1.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.05, max=1.0)),
            vol.Optional(
                "order",
                description="Light order used by chase, scan and streak",
                default="Position",
            ): vol.In(ORDERS),
            vol.Optional(
                "band",
                description="Frequency band the reactive level listens to",
                default="Full",
            ): vol.In(BANDS),
            vol.Optional(
                "reactive_depth",
                description="How much the band level scales the brightness. 0 runs on the beat alone, 1 follows the level fully",
                default=0.0,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "threshold",
                description="gate and burst: level the band must exceed",
                default=0.2,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=0.99)),
            vol.Optional(
                "sensitivity",
                description="Gain on the audio levels",
                default=0.5,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "smoothing",
                description="How much the audio levels are smoothed",
                default=0.35,
            ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
            vol.Optional(
                "flash_limit",
                description="Keep any lamp from jumping to bright more than about three times a second",
                default=True,
            ): bool,
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
        self._seed = int(self._rng.integers(1, 2**31))
        self._stepper = StepTrigger(self._config, now)
        self._events = []  # (start time, index)
        self._event_index = -1
        self._last_burst = -np.inf
        self._band_masks = None
        self._band_freq_count = 0
        self._levels = np.zeros(4)  # full, bass, mids, high
        self._last_level_time = now
        self._build_zones(pixel_count)
        self._reset_lamps()
        self._step(now)

    def config_updated(self, config):
        self.family = self._config["family"]
        self.shape = SHAPES[self._config["shape"]]
        self.color = np.array(parse_color(self._config["color"]), dtype=float)
        self.curve_kind = self._config["curve"]
        self.direction = self._config["direction"]
        self.attack = self._config["attack"]
        self.hold = self._config["hold"]
        self.release = self._config["release"]
        self.stagger = self._config["stagger"]
        self.trail = self._config["trail"]
        self.probability = self._config["probability"]
        self.origin = self._config["origin"]
        self.radius = self._config["radius"]
        self.band = self.BANDS.index(self._config["band"])
        self.reactive_depth = self._config["reactive_depth"]
        self.threshold = self._config["threshold"]
        self.gain = 1.0 + 5.0 * self._config["sensitivity"]
        scale = 1.0 + 4.0 * self._config["smoothing"]
        self.level_attack = self.LEVEL_ATTACK * scale
        self.level_release = self.LEVEL_RELEASE * scale
        self.flash_limit = self._config["flash_limit"]
        self._band_masks = None
        if getattr(self, "_stepper", None) is not None:
            self._stepper.configure(self._config)
        if getattr(self, "pixels", None) is not None:
            self._build_zones(self.pixel_count)
            if len(self._lamp_was_bright) != self._zone_count:
                self._reset_lamps()
            else:
                self._order_lamps()

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

    def _reset_lamps(self):
        n = self._zone_count
        self._lamp_was_bright = np.zeros(n, dtype=bool)
        self._lamp_last_rise = np.full(n, -np.inf)
        self._order_lamps()

    def _order_lamps(self):
        """Rank of every lamp in the light order, and its position 0..1."""
        n = self._zone_count
        if self._config["order"] == "Random":
            self._rank = np.argsort(hash01(self._seed, np.arange(n) + 1, 0))
            self._rank = np.argsort(self._rank)
        else:
            self._rank = np.arange(n)
        self._position = self._rank / max(1, n - 1)

    # ---------------------------------------------------------------- audio

    def _masks_for(self, frequencies):
        frequencies = np.asarray(frequencies)
        if self._band_masks is None or self._band_freq_count != len(
            frequencies
        ):
            masks = []
            for low, high in self.BAND_EDGES:
                mask = (frequencies >= low) & (frequencies <= high)
                if not mask.any():
                    mask[np.argmin(np.abs(frequencies - (low + high) / 2))] = (
                        True
                    )
                masks.append(mask)
            self._band_masks = masks
            self._band_freq_count = len(frequencies)
        return self._band_masks

    def measure(self, melbank, frequencies, now):
        """Update the smoothed full, bass, mids and high levels from a frame."""
        melbank = np.nan_to_num(np.asarray(melbank, dtype=float))
        masks = self._masks_for(frequencies)
        full = min(1.0, float(np.mean(melbank)) * self.gain)
        total = float(np.sum(melbank))
        raw = np.zeros(4)
        raw[0] = full
        if total > 1e-9:
            for i, mask in enumerate(masks):
                share = float(np.sum(melbank[mask])) / total
                raw[i + 1] = min(1.0, full * np.sqrt(min(1.0, share)) * 1.8)

        elapsed = max(0.001, min(0.5, now - self._last_level_time))
        self._last_level_time = now
        rising = raw >= self._levels
        tau = np.where(rising, self.level_attack, self.level_release)
        alpha = 1.0 - np.exp(-elapsed / tau)
        self._levels = self._levels + (raw - self._levels) * alpha
        return self._levels

    def audio_data_updated(self, data):
        now = timeit.default_timer()
        self._stepper.audio(data, now)
        melbanks = data.melbanks
        self.measure(
            melbanks.melbanks[-1],
            melbanks.melbank_processors[-1].melbank_frequencies,
            now,
        )

    # --------------------------------------------------------------- events

    def _beat_period(self):
        stepper = self._stepper
        return max(0.05, stepper.step_interval * stepper.steps_per_beat)

    def _envelope_length(self):
        return (self.attack + self.hold + self.release) * self._beat_period()

    def _step(self, now):
        """A new event starts on every step."""
        if (
            self.family == "burst"
            and now - self._last_burst < self.BURST_INTERVAL
        ):
            return
        if self.family == "burst":
            self._last_burst = now
        self._event_index += 1
        self._events.append((now, self._event_index))

    def _prune_events(self, now):
        keep = self._envelope_length()
        if self.family == "chase":
            keep += self.stagger * self._beat_period() * self._zone_count
        elif self.family == "adsr":
            keep = self._stepper.step_interval
        self._events = [
            (start, index)
            for start, index in self._events
            if now - start < keep + 0.05
        ]

    def _reversed(self, event):
        if self.direction == "reverse":
            return True
        if self.direction == "alternate":
            return event % 2 == 1
        if self.direction == "random":
            return float(hash01(self._seed, [0], event)[0]) >= 0.5
        return False

    def _envelope(self, age):
        """Family envelope over the age of an event, vectorised."""
        beat = self._beat_period()
        attack = self.attack * beat
        hold = self.hold * beat
        release = self.release * beat
        total = attack + hold + release
        age = np.asarray(age, dtype=float)
        if total <= 0.0:
            return np.where(age == 0.0, 1.0, 0.0)
        if self.curve_kind == "cut":
            return np.where((age >= 0.0) & (age < attack + hold), 1.0, 0.0)
        out = np.zeros_like(age)
        if attack > 0:
            rising = (age >= 0.0) & (age < attack)
            out[rising] = curve(age[rising] / attack, self.curve_kind)
        holding = (age >= attack) & (age < attack + hold)
        out[holding] = 1.0
        if release > 0:
            falling = (age >= attack + hold) & (age < total)
            out[falling] = 1.0 - curve(
                (age[falling] - attack - hold) / release, self.curve_kind
            )
        return out

    # -------------------------------------------------------------- kernels

    @staticmethod
    def _smoothstep(start, end, value):
        t = np.clip((value - start) / max(1e-9, end - start), 0.0, 1.0)
        return t * t * (3.0 - 2.0 * t)

    @staticmethod
    def _raised_cosine(phase):
        return (np.cos((phase % 1.0) * 2.0 * np.pi) + 1.0) / 2.0

    def _kernel(self, event, progress, envelope_length):
        """
        Strength and palette position of every lamp for one event.

        progress: age / envelope length of the event, 0..1 (before any
        per lamp stagger, which is applied by the caller for chase).
        """
        n = self._zone_count
        reverse = self._reversed(event)
        rank = (n - 1 - self._rank) if reverse else self._rank
        position = rank / max(1, n - 1)
        p = (1.0 - progress) if reverse else progress
        family = self.family

        if family == "chase":
            return np.ones(n), (rank + event) / n

        if family == "radial":
            origin = self.origin
            extent = max(origin, 1.0 - origin)
            distance = np.abs(self._position - origin) / (
                max(0.05, self.radius) * extent
            )
            strength = 1.0 - self._smoothstep(0.12, 0.45, np.abs(distance - p))
            return strength, distance + p

        if family in ("wash", "gate"):
            gated = family == "gate"
            spread = 1.0 if gated else max(0.08, self.radius)
            phase = position / spread - p + event * 0.11
            lobes = np.maximum(
                self._raised_cosine(phase),
                np.maximum(
                    self._raised_cosine(phase + 1.0 / 3.0),
                    self._raised_cosine(phase + 2.0 / 3.0),
                ),
            )
            strength = (
                (0.72 + 0.28 * lobes) if gated else (0.55 + 0.45 * lobes)
            )
            return strength, phase

        if family == "scan":
            head = 1.0 - abs(p * 2.0 - 1.0)
            width = np.clip(
                self.trail * self._beat_period() / envelope_length, 0.035, 0.7
            )
            strength = np.exp(-4.5 * ((position - head) / width) ** 2)
            return strength, head + position

        if family == "streak":
            roll = float(hash01(self._seed, [0], event)[0])
            if roll > self.probability:
                return np.zeros(n), np.full(n, roll)
            width = np.clip(
                self.trail * self._beat_period() / envelope_length, 0.03, 0.95
            )
            behind = p - position
            strength = np.where(
                (behind >= 0.0) & (behind <= width * 4.0),
                np.exp(-3.2 * behind / width),
                0.0,
            )
            return strength, p + position + roll

        if family == "twinkle":
            roll = hash01(self._seed, np.arange(n) + 1, event)
            return (
                np.where(roll <= self.probability, 1.0, 0.0),
                roll + event * 0.07,
            )

        if family == "burst":
            roll = hash01(self._seed, np.arange(n) + 1, event * 17)
            return (
                np.where(roll < self.probability, 1.0, 0.0),
                roll + event * 0.31,
            )

        # breathe
        return np.ones(n), np.full(n, progress + event * 0.17)

    # --------------------------------------------------------------- render

    def _trigger_strength(self):
        """How much the music level scales the show right now."""
        depth = self.reactive_depth
        level = float(np.clip(self._levels[self.band], 0.0, 1.0))
        if self.family in ("gate", "burst"):
            floor = min(0.99, self.threshold)
            level = max(0.0, (level - floor) / (1.0 - floor))
            if self.family == "gate":
                depth = max(depth, 0.8)
            else:
                depth = max(depth, 0.6)
        return 1.0 - depth + level * depth

    def _limit_flashes(self, brightness, now):
        """Suppress a rise to bright that follows the previous one too soon."""
        if not self.flash_limit:
            return brightness
        bright = brightness >= self.FLASH_BRIGHT
        rising = bright & ~self._lamp_was_bright
        too_soon = rising & (now - self._lamp_last_rise < self.FLASH_INTERVAL)
        allowed = rising & ~too_soon
        self._lamp_last_rise[allowed] = now
        self._lamp_was_bright = bright & ~too_soon
        return np.where(too_soon, 0.0, brightness)

    def _render_adsr(self, now):
        n = self._zone_count
        if not self._events:
            return np.zeros((n, 3))
        start, _ = self._events[-1]
        progress = (now - start) / max(0.05, self._stepper.step_interval)
        shape = self.shape
        if shape.get("single"):
            level = ahdsr(shape["brightness"], progress, self.curve_kind)
            rgb = self.color / 255.0 * level
        else:
            rgb = np.array(
                [
                    ahdsr(shape[channel], progress, self.curve_kind)
                    for channel in ("red", "green", "blue")
                ]
            )
        peak = float(rgb.max())
        if peak <= 0.0:
            return np.zeros((n, 3))
        color = rgb / peak * 255.0
        return np.tile(color * peak, (n, 1))

    def _render_families(self, now):
        n = self._zone_count
        beat = self._beat_period()
        length = max(0.05, self._envelope_length())
        best = np.zeros(n)
        best_event = np.full(n, -1)
        palette = np.zeros(n)
        for start, event in self._events:
            age = now - start
            if self.family == "chase":
                rank = (
                    (n - 1 - self._rank)
                    if self._reversed(event)
                    else self._rank
                )
                age = age - rank * self.stagger * beat
            else:
                age = np.full(n, age)
            envelope = self._envelope(age)
            if not np.any(envelope > 0.0):
                continue
            progress = (
                float(np.clip(np.max(age) / length, 0.0, 1.0))
                if self.family != "chase"
                else None
            )
            if self.family == "chase":
                strength, pos = self._kernel(event, 0.0, length)
            else:
                strength, pos = self._kernel(event, progress, length)
            value = np.clip(envelope * strength, 0.0, 1.0)
            better = (value > best) | (
                (np.abs(value - best) < 1e-6)
                & (event > best_event)
                & (value > 0)
            )
            best = np.where(better, value, best)
            palette = np.where(better, pos, palette)
            best_event = np.where(better, event, best_event)

        brightness = best * self._trigger_strength()
        colors = self.get_gradient_color_vectorized1d(palette % 1.0)
        return colors, brightness

    def render(self):
        now = self.now
        if self._stepper.poll(now):
            self._step(now)
        self._prune_events(now)

        if self.family == "adsr":
            out = self._render_adsr(now)
            brightness = out.max(axis=1) / 255.0
            limited = self._limit_flashes(brightness, now)
            with np.errstate(invalid="ignore", divide="ignore"):
                scale = np.where(brightness > 0, limited / brightness, 0.0)
            out = out * scale[:, None]
        else:
            colors, brightness = self._render_families(now)
            brightness = self._limit_flashes(brightness, now)
            out = colors * brightness[:, None]

        self.pixels[:] = out[self._zone_of_pixel]
