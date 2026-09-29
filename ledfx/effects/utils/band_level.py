"""
Smoothed level of one frequency band, shared by the party mode effects.

The level is the mean melbank energy of the band, scaled by a gain, with
a fast attack and a slower release so that accents show and the level
falls back smoothly between them.
"""

import numpy as np
import voluptuous as vol

BANDS = ["Full", "Bass", "Mids", "High"]

# Hz edges of the bands, Full spans the whole melbank
BAND_EDGES = {
    "Full": (0.0, float("inf")),
    "Bass": (20.0, 250.0),
    "Mids": (250.0, 3000.0),
    "High": (3000.0, 9000.0),
}


def band_level_schema(band="Full", reactive_depth=0.3):
    """Schema entries for a reactive band level, with the given defaults."""
    return {
        vol.Optional(
            "band",
            description="Frequency band the music level follows",
            default=band,
        ): vol.In(BANDS),
        vol.Optional(
            "reactive_depth",
            description="How much the music level scales the brightness, 0 ignores the level",
            default=reactive_depth,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.0, max=1.0)),
        vol.Optional(
            "sensitivity",
            description="Gain on the music level",
            default=1.0,
        ): vol.All(vol.Coerce(float), vol.Range(min=0.1, max=4.0)),
    }


def frequency_key(frequencies):
    """A cheap key that changes whenever the melbank frequency axis does."""
    frequencies = np.asarray(frequencies, dtype=float)
    if len(frequencies) == 0:
        return (0, 0.0, 0.0)
    return (len(frequencies), float(frequencies[0]), float(frequencies[-1]))


def band_masks(frequencies, edges):
    """
    Boolean melbank masks for a list of (low, high) Hz bands.

    A band narrower than the melbank resolution takes the nearest bin so
    that it still does something.
    """
    frequencies = np.asarray(frequencies, dtype=float)
    masks = []
    for low, high in edges:
        low, high = min(low, high), max(low, high)
        mask = (frequencies >= low) & (frequencies <= high)
        if not mask.any() and len(frequencies):
            mask[np.argmin(np.abs(frequencies - (low + high) / 2))] = True
        masks.append(mask)
    return masks


class BandLevel:
    """One smoothed band level, fed from the melbank."""

    # Rise and fall time constants of the level in seconds
    ATTACK = 0.03
    RELEASE = 0.22
    # Melbank mean that counts as full level at gain 1
    FULL_SCALE = 0.5

    def __init__(self, band="Full", sensitivity=1.0, now=0.0):
        self.configure(band, sensitivity)
        self.level = 0.0
        self._last_time = now
        self._mask = None
        self._mask_key = None

    def configure(self, band, sensitivity):
        self.band = band if band in BAND_EDGES else "Full"
        self.gain = float(sensitivity) / self.FULL_SCALE

    def _mask_for(self, frequencies):
        frequencies = np.asarray(frequencies, dtype=float)
        key = (self.band, frequency_key(frequencies))
        if self._mask_key != key:
            low, high = BAND_EDGES[self.band]
            mask = (frequencies >= low) & (frequencies <= high)
            if not mask.any():
                mask[:] = True
            self._mask = mask
            self._mask_key = key
        return self._mask

    def update(self, melbank, frequencies, now):
        """Feed one melbank frame, returns the smoothed level from 0 to 1."""
        melbank = np.nan_to_num(np.asarray(melbank, dtype=float))
        mask = self._mask_for(frequencies)
        raw = min(1.0, float(np.mean(melbank[mask])) * self.gain)

        elapsed = max(0.001, min(0.5, now - self._last_time))
        self._last_time = now
        tau = self.ATTACK if raw >= self.level else self.RELEASE
        alpha = 1.0 - np.exp(-elapsed / tau)
        self.level = self.level + (raw - self.level) * alpha
        return self.level

    def scale(self, reactive_depth):
        """Brightness factor: 1 at depth 0, the level itself at depth 1."""
        depth = float(reactive_depth)
        return 1.0 - depth + depth * min(1.0, max(0.0, self.level))
