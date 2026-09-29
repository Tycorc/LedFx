"""Unit tests for the Disco (sound to light) effect."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import voluptuous as vol

from ledfx.effects import Effect
from ledfx.effects.disco import DiscoEffect, validate_light_map

# A melbank style frequency axis, 64 log spaced bins from 20 Hz to 15 kHz
FREQS = np.geomspace(20, 15000, 64)
BASS = (FREQS >= 40) & (FREQS <= 180)
VOICE = (FREQS >= 220) & (FREQS <= 2000)
TREBLE = (FREQS >= 3000) & (FREQS <= 12000)


def make_effect(pixel_count=6, **config):
    effect = DiscoEffect(ledfx=MagicMock(), config=config)
    virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    Effect.activate(effect, virtual)
    effect.now = 0.0
    return effect


def render_at(effect, t):
    effect.now = t
    effect.render()
    return np.copy(effect.pixels)


def melbank(bass=0.0, voice=0.0, treble=0.0):
    frame = np.zeros(len(FREQS))
    frame[BASS] = bass
    frame[VOICE] = voice
    frame[TREBLE] = treble
    return frame


def feed(effect, frame, t, frames=1, spacing=0.02):
    """Feed the same frame a few times, returns the hits of the last one."""
    hits = None
    for i in range(frames):
        hits = effect.analyse(frame, FREQS, t + i * spacing)
    return hits


def settle(effect, t=-5.0):
    """Feed silence long enough for the running averages to settle."""
    feed(effect, melbank(), t, frames=50)


def lit_lamps(pixels):
    return [int(i) for i in np.flatnonzero(pixels.max(axis=1) > 0)]


class FakeAudio:
    """Enough of AudioAnalysisSource for audio_data_updated."""

    def __init__(self, frame):
        processor = SimpleNamespace(melbank_frequencies=FREQS)
        self.melbanks = SimpleNamespace(
            melbanks=(frame,), melbank_processors=[processor]
        )


# ----------------------------------------------------------- assignment


def test_interleaved_assignment_alternates_the_channels():
    effect = make_effect(pixel_count=6)
    assert list(effect._lamp_channel) == [0, 1, 2, 0, 1, 2]


def test_blocks_assignment_groups_the_lamps():
    effect = make_effect(pixel_count=6, assignment="Blocks")
    assert list(effect._lamp_channel) == [0, 0, 1, 1, 2, 2]


def test_all_lights_assignment_marks_every_lamp_as_loudest():
    effect = make_effect(pixel_count=3, assignment="All lights")
    assert list(effect._lamp_channel) == [-2, -2, -2]


def test_disabled_channels_are_skipped():
    effect = make_effect(pixel_count=4, voice=False)
    assert list(effect._lamp_channel) == [0, 2, 0, 2]
    off = make_effect(pixel_count=2, bass=False, voice=False, treble=False)
    assert list(off._lamp_channel) == [-1, -1]


def test_light_map_overrides_the_assignment():
    effect = make_effect(pixel_count=5, light_map="bv-t")
    assert list(effect._lamp_channel) == [0, 1, -1, 2, 0]


def test_light_map_ignores_disabled_channels():
    effect = make_effect(pixel_count=3, light_map="BVT", treble=False)
    assert list(effect._lamp_channel) == [0, 1, -1]


def test_light_map_rejects_other_letters():
    assert validate_light_map(" b v t ") == "BVT"
    with pytest.raises(vol.Invalid):
        validate_light_map("BVX")


def test_zones_split_long_strips():
    effect = make_effect(pixel_count=300)
    assert effect._zone_count == DiscoEffect.AUTO_ZONE_COUNT


# ------------------------------------------------------------- analysis


def test_band_powers_average_each_band():
    masks = [BASS, VOICE, TREBLE]
    powers = DiscoEffect.band_powers(melbank(0.5, 0.2, 0.9), masks)
    assert np.allclose(powers, [0.5, 0.2, 0.9])


def test_band_masks_follow_the_configured_edges():
    effect = make_effect(bass_low=20, bass_high=60, treble_low=10000)
    masks = effect._masks_for(FREQS)
    assert FREQS[masks[0]].max() <= 60
    assert FREQS[masks[2]].min() >= 10000


def test_narrow_band_falls_back_to_the_nearest_bin():
    effect = make_effect(bass_low=1000, bass_high=1001)
    masks = effect._masks_for(FREQS)
    assert masks[0].sum() == 1


def test_bass_hit_triggers_only_the_bass_channel():
    effect = make_effect()
    settle(effect)
    hits = feed(effect, melbank(bass=0.8), 0.0)
    assert list(hits) == [True, False, False]


def test_hits_need_a_jump_above_the_running_average():
    effect = make_effect()
    # A steady bass level raises the average until it stops triggering
    hits = feed(effect, melbank(bass=0.2), 0.0, frames=200)
    assert not hits[0]
    # A clear jump above that level is a hit again
    hits = feed(effect, melbank(bass=0.9), 5.0)
    assert hits[0]


def test_hits_are_rate_limited_per_channel():
    effect = make_effect()
    settle(effect)
    assert feed(effect, melbank(bass=0.9), 0.0)[0]
    assert not feed(effect, melbank(bass=0.9), 0.05)[0]
    assert feed(effect, melbank(bass=0.9), 0.05 + DiscoEffect.HIT_MIN_GAP)[0]


def test_low_sensitivity_needs_more_power():
    quiet = make_effect(sensitivity=0.0)
    loud = make_effect(sensitivity=1.0)
    for effect in (quiet, loud):
        settle(effect)
    assert not feed(quiet, melbank(bass=0.15), 0.0)[0]
    assert feed(loud, melbank(bass=0.15), 0.0)[0]


def test_audio_data_updated_reads_the_full_range_melbank():
    effect = make_effect()
    settle(effect)
    effect.audio_data_updated(FakeAudio(melbank(treble=0.9)))
    assert effect._power[2] > 0
    assert effect._power[0] == 0


# --------------------------------------------------------------- render


def test_spectrum_hit_lights_the_channel_lamps_only():
    effect = make_effect(pixel_count=6)
    settle(effect)
    feed(effect, melbank(voice=0.9), 0.0)
    pixels = render_at(effect, 0.0)
    assert lit_lamps(pixels) == [1, 4]
    assert np.array_equal(pixels[1], pixels[4])


def test_pulse_fades_after_a_hit():
    effect = make_effect(pixel_count=3, fast_pulse=False, smoothness=0.0)
    settle(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    peak = render_at(effect, 0.0)[0].max()
    later = render_at(effect, DiscoEffect.SLOW_PULSE_TAU)[0].max()
    gone = render_at(effect, 5.0)[0].max()
    assert peak == pytest.approx(effect._colors[0].max(), abs=1)
    assert later == pytest.approx(peak / np.e, abs=2)
    assert gone < 1


def test_fast_pulse_is_shorter_than_slow():
    fast = make_effect(pixel_count=3, fast_pulse=True)
    slow = make_effect(pixel_count=3, fast_pulse=False)
    assert fast.pulse_tau < slow.pulse_tau
    assert make_effect(smoothness=1.0).pulse_tau > make_effect().pulse_tau


def test_without_fade_the_lamps_follow_the_band_level():
    effect = make_effect(pixel_count=3, fade=False, smoothness=0.0)
    feed(effect, melbank(bass=0.25), 0.0, frames=20)
    half = render_at(effect, 0.0)[0].max()
    feed(effect, melbank(), 1.0, frames=50)
    quiet = render_at(effect, 1.0)[0].max()
    assert half > 0
    assert quiet < half


def test_hit_changes_the_channel_colour():
    effect = make_effect(pixel_count=3)
    settle(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    first = render_at(effect, 0.0)[0]
    feed(effect, melbank(bass=0.9), 1.0)
    second = render_at(effect, 1.0)[0]
    assert not np.array_equal(first, second)


def test_intensity_and_idle_brightness_scale_the_pulse():
    effect = make_effect(pixel_count=3, intensity=0.5, idle_brightness=0.2)
    settle(effect)
    before = render_at(effect, -1.0)[0]
    assert np.allclose(before, effect._colors[0] * 0.2, atol=1)
    feed(effect, melbank(bass=0.9), 0.0)
    at_hit = render_at(effect, 0.0)[0]
    color = effect._colors[0]
    assert np.allclose(at_hit, color * (0.2 + 0.8 * 0.5), atol=1)


def test_peak_mode_pulses_every_lamp_together():
    effect = make_effect(pixel_count=4, mode="Peak", bass=False)
    settle(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    pixels = render_at(effect, 0.0)
    assert lit_lamps(pixels) == [0, 1, 2, 3]
    assert np.all(pixels == pixels[0])


def test_peak_strobe_flashes_the_strobe_colour_first():
    effect = make_effect(
        pixel_count=2, mode="Peak", strobe=True, strobe_color="#00ff00"
    )
    settle(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    assert np.allclose(render_at(effect, 0.0), [0, 255, 0], atol=1)
    after = render_at(effect, DiscoEffect.STROBE_TIME + 0.01)
    assert not np.allclose(after, [0, 255, 0], atol=1) or np.allclose(
        effect._colors[0], [0, 255, 0], atol=1
    )


def test_all_lights_shows_the_loudest_channel():
    effect = make_effect(pixel_count=3, assignment="All lights")
    settle(effect)
    feed(effect, melbank(treble=0.9), 0.0)
    pixels = render_at(effect, 0.0)
    assert lit_lamps(pixels) == [0, 1, 2]
    assert np.allclose(pixels[0], effect._colors[2], atol=1)


def test_neural_brightness_follows_loudness_and_colour_the_balance():
    effect = make_effect(
        pixel_count=3,
        mode="Neural",
        smoothness=0.0,
        modulate_saturation=False,
    )
    dark = render_at(effect, 0.0)
    feed(effect, melbank(bass=0.5), 0.0, frames=40)
    bassy = render_at(effect, 1.0)
    feed(effect, melbank(treble=0.5), 2.0, frames=40)
    bright = render_at(effect, 3.0)
    assert dark.max() == 0
    assert bassy.max() > 0 and bright.max() > 0
    assert effect._centroid > 0.5
    assert not np.allclose(bassy / bassy.max(), bright / bright.max())


def test_neural_transients_wash_towards_white():
    effect = make_effect(pixel_count=1, mode="Neural", smoothness=0.0)
    feed(effect, melbank(voice=0.05), 0.0, frames=100)
    steady = render_at(effect, 1.0)[0]
    feed(effect, melbank(voice=0.6), 2.0)
    burst = render_at(effect, 2.0)[0]
    # A burst is brighter and less saturated than the steady state
    assert burst.max() > steady.max()
    assert burst.min() / burst.max() > steady.min() / max(1, steady.max())


def test_config_update_reassigns_lamps():
    effect = make_effect(pixel_count=4)
    effect.update_config({"assignment": "Blocks", "treble": False})
    assert list(effect._lamp_channel) == [0, 0, 1, 1]
    settle(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    assert lit_lamps(render_at(effect, 0.0)) == [0, 1]
