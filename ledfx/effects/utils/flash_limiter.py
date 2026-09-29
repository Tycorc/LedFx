"""
Photosensitivity guard for the party mode effects.

No lamp is allowed to jump to bright more often than about three times a
second whatever the settings say. A rise that comes too soon after the
previous one is held dark until the interval has passed.
"""

import numpy as np


class FlashLimiter:
    """Limits how often every lamp may rise to bright."""

    # A jump to at least this brightness counts as a flash
    BRIGHT = 0.55
    # Minimum seconds between two flashes of one lamp
    INTERVAL = 0.35

    def __init__(self, count, enabled=True):
        self.enabled = enabled
        self.reset(count)

    def reset(self, count):
        self._last_rise = np.full(count, -np.inf)
        self._was_bright = np.zeros(count, dtype=bool)

    def apply(self, brightness, now):
        """Return the brightness with the too frequent rises suppressed."""
        brightness = np.asarray(brightness, dtype=float)
        if not self.enabled:
            return brightness
        if len(brightness) != len(self._last_rise):
            self.reset(len(brightness))
        bright = brightness >= self.BRIGHT
        rising = bright & ~self._was_bright
        too_soon = rising & (now - self._last_rise < self.INTERVAL)
        allowed = rising & ~too_soon
        self._last_rise[allowed] = now
        self._was_bright = bright & ~too_soon
        return np.where(too_soon, 0.0, brightness)
