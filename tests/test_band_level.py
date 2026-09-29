"""Unit tests for the shared band level and flash limiter helpers."""

import numpy as np
import pytest
import voluptuous as vol

from ledfx.effects.utils.band_level import (
    BANDS,
    BandLevel,
    band_level_schema,
)
from ledfx.effects.utils.flash_limiter import FlashLimiter

FREQS = np.geomspace(20, 15000, 64)


def frame(bass=0.0, mids=0.0, high=0.0):
    melbank = np.zeros(len(FREQS))
    melbank[(FREQS >= 20) & (FREQS < 250)] = bass
    melbank[(FREQS >= 250) & (FREQS < 3000)] = mids
    melbank[(FREQS >= 3000) & (FREQS <= 9000)] = high
    return melbank


def test_schema_defaults_and_bounds():
    schema = vol.Schema(band_level_schema())
    config = schema({})
    assert config["band"] == "Full"
    assert config["reactive_depth"] == 0.3
    assert config["sensitivity"] == 1.0
    with pytest.raises(vol.Invalid):
        schema({"band": "Sub"})
    for band in BANDS:
        assert schema({"band": band})["band"] == band


def test_level_follows_its_own_band_only():
    level = BandLevel("Bass", sensitivity=1.0, now=0.0)
    for i in range(1, 30):
        level.update(frame(mids=0.8, high=0.8), FREQS, i * 0.02)
    assert level.level == pytest.approx(0.0)
    for i in range(30, 60):
        level.update(frame(bass=0.5), FREQS, i * 0.02)
    assert level.level > 0.9


def test_level_rises_fast_and_falls_slowly():
    level = BandLevel("Full", now=0.0)
    level.update(frame(bass=1.0, mids=1.0, high=1.0), FREQS, 0.03)
    after_attack = level.level
    assert after_attack > 0.5
    level.update(frame(), FREQS, 0.06)
    assert level.level > after_attack * 0.8
    for i in range(2, 60):
        level.update(frame(), FREQS, 0.03 * i)
    assert level.level < 0.01


def test_level_gain_and_scale():
    level = BandLevel("Full", sensitivity=4.0, now=0.0)
    level.update(frame(bass=0.2, mids=0.2, high=0.2), FREQS, 5.0)
    assert level.level == pytest.approx(1.0, abs=1e-6)
    assert level.scale(0.0) == 1.0
    assert level.scale(1.0) == pytest.approx(1.0)
    level.level = 0.25
    assert level.scale(1.0) == pytest.approx(0.25)
    assert level.scale(0.5) == pytest.approx(0.625)


def test_unknown_band_falls_back_to_full():
    level = BandLevel("Nope")
    assert level.band == "Full"


def test_flash_limiter_holds_a_second_rise_that_comes_too_soon():
    limiter = FlashLimiter(2)
    on = np.array([1.0, 1.0])
    off = np.zeros(2)
    assert limiter.apply(on, 0.0).tolist() == [1.0, 1.0]
    limiter.apply(off, 0.1)
    assert limiter.apply(on, 0.2).tolist() == [0.0, 0.0]
    limiter.apply(off, 0.3)
    assert limiter.apply(on, 0.4).tolist() == [1.0, 1.0]


def test_flash_limiter_ignores_dim_and_held_lamps():
    limiter = FlashLimiter(1)
    assert limiter.apply(np.array([1.0]), 0.0).tolist() == [1.0]
    # Staying bright is not a new rise
    assert limiter.apply(np.array([1.0]), 0.1).tolist() == [1.0]
    limiter.apply(np.array([0.0]), 0.2)
    assert limiter.apply(np.array([0.4]), 0.25).tolist() == [0.4]


def test_flash_limiter_can_be_disabled_and_resized():
    limiter = FlashLimiter(1, enabled=False)
    assert limiter.apply(np.array([1.0]), 0.0).tolist() == [1.0]
    assert limiter.apply(np.array([1.0]), 0.05).tolist() == [1.0]
    limiter = FlashLimiter(1)
    assert limiter.apply(np.array([1.0, 1.0, 1.0]), 0.0).shape == (3,)
