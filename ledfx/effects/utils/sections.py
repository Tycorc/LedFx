"""
Sections of a track: quiet, soft and loud parts, drops, and palette changes.

A DJ light show does not play the same thing through a whole track. The
quiet intro gets a slow drift, the verses a soft show, the drops the hard
patterns, and every so often the palette changes. The SectionDetector turns
a music level into that structure: with an automatic gain so that a quiet
recording and a loud one give the same sections, hysteresis and a minimum
section length so that the show does not flicker between them, a drop event
when the music comes back loud after a build, and a palette change every
few seconds that lands on a bar boundary.
"""

import math
import random

SECTIONS = ["quiet", "soft", "loud"]


class SectionDetector:
    """Follows the loud, soft and quiet sections of the music."""

    # The level is normalised by a slow peak that forgets over this many
    # seconds, so the sections adapt to the loudness of the recording
    PEAK_DECAY = 20.0
    PEAK_FLOOR = 0.05
    # Fast level for drops, in seconds
    FAST_ATTACK = 0.03
    FAST_RELEASE = 0.3
    # Slow level for sections, in seconds
    ATTACK = 0.25
    RELEASE = 2.0
    # Section thresholds on the normalised slow level, with hysteresis
    QUIET_BELOW = 0.15
    LOUD_ABOVE = 0.55
    HYSTERESIS = 0.05
    # A section lasts at least this long before the next change
    MIN_SECTION = 2.0
    # A drop: the fast level jumps above DROP_LEVEL after at least
    # DROP_BUILD seconds without being that loud
    DROP_LEVEL = 0.7
    DROP_BUILD = 4.0
    # Longest a palette change waits for a bar boundary
    BAR_WAIT = 4.0
    # Palette offset moves at least this far on every change
    MIN_PALETTE_STEP = 0.25

    def __init__(self, now=0.0, palette_interval=12.0, seed=None):
        self.palette_interval = max(1.0, float(palette_interval))
        self._random = random.Random(seed)
        self.reset(now)

    def reset(self, now):
        self.section = "quiet"
        self.level = 0.0
        self.fast = 0.0
        self.changed = False
        self.drop = False
        self.palette_offset = 0.0
        self.palette_changed = False
        self._peak = self.PEAK_FLOOR
        self._last_time = now
        self._section_since = now
        self._last_loud_time = now
        self._next_palette = now + self._jittered_interval()
        self._palette_pending = False
        self._palette_waiting_since = now
        self._last_bar_phase = None

    def _jittered_interval(self):
        return self.palette_interval * (0.75 + 0.5 * self._random.random())

    def _target_section(self):
        level = self.level
        if self.section == "loud":
            if level < self.LOUD_ABOVE - self.HYSTERESIS:
                return "quiet" if level < self.QUIET_BELOW else "soft"
            return "loud"
        if self.section == "quiet":
            if level >= self.QUIET_BELOW + self.HYSTERESIS:
                return "loud" if level >= self.LOUD_ABOVE else "soft"
            return "quiet"
        if level >= self.LOUD_ABOVE:
            return "loud"
        if level < self.QUIET_BELOW:
            return "quiet"
        return "soft"

    def update(self, raw, now, bar_phase=None):
        """
        Feed one music level, returns the current section.

        raw is any non negative loudness measure (a band level, the melbank
        mean...), bar_phase the bar oscillator when known so that palette
        changes land on a bar. Sets changed, drop and palette_changed for
        this frame.
        """
        raw = max(0.0, float(raw))
        elapsed = max(0.001, min(0.5, now - self._last_time))
        self._last_time = now
        self.changed = False
        self.drop = False
        self.palette_changed = False

        # Automatic gain
        self._peak = max(
            raw,
            self.PEAK_FLOOR,
            self._peak * math.exp(-elapsed / self.PEAK_DECAY),
        )
        normalised = min(1.0, raw / self._peak)

        tau = self.FAST_ATTACK if normalised >= self.fast else self.FAST_RELEASE
        self.fast += (normalised - self.fast) * (1.0 - math.exp(-elapsed / tau))
        tau = self.ATTACK if normalised >= self.level else self.RELEASE
        self.level += (normalised - self.level) * (1.0 - math.exp(-elapsed / tau))

        # Drops
        if self.fast >= self.DROP_LEVEL:
            if now - self._last_loud_time >= self.DROP_BUILD:
                self.drop = True
            self._last_loud_time = now

        # Sections
        target = "loud" if self.drop else self._target_section()
        if target != self.section and (
            self.drop or now - self._section_since >= self.MIN_SECTION
        ):
            self.section = target
            self._section_since = now
            self.changed = True

        # Palette changes, on a bar boundary when one is known
        if not self._palette_pending and now >= self._next_palette:
            self._palette_pending = True
            self._palette_waiting_since = now
        if self._palette_pending:
            new_bar = (
                bar_phase is not None
                and self._last_bar_phase is not None
                and bar_phase < self._last_bar_phase
            )
            waited = now - self._palette_waiting_since
            if bar_phase is None or new_bar or waited >= self.BAR_WAIT:
                step = self.MIN_PALETTE_STEP + self._random.random() * (
                    1.0 - 2 * self.MIN_PALETTE_STEP
                )
                self.palette_offset = (self.palette_offset + step) % 1.0
                self.palette_changed = True
                self._palette_pending = False
                self._next_palette = now + self._jittered_interval()
        self._last_bar_phase = bar_phase

        return self.section

    def time_in_section(self, now):
        """Seconds since the current section started."""
        return now - self._section_since
