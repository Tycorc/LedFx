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

RED_BLUE = "linear-gradient(90deg, #ff0000 0%, #ff0000 50%, #0000ff 50%, #0000ff 100%)"


def make_effect(pixel_count=6, **config):
    effect = DiscoEffect(ledfx=MagicMock(), config=config)
    virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    Effect.activate(effect, virtual)
    # Rebase every clock so tests can use small numbers: activation was at
    # -1 s, so hits at t >= 0 clear the minimum gap and idle starts at 1 s
    effect._hit_time[:] = -1.0
    effect._last_frame_time = 0.0
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


def warm_up(effect, t=-10.0, frame=None):
    """Fill the energy history with quiet music so hits can trigger."""
    feed(
        effect,
        frame if frame is not None else melbank(0.02, 0.02, 0.02),
        t,
        frames=100,
    )


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


def test_all_lights_assignment_flashes_every_lamp_on_every_channel():
    effect = make_effect(pixel_count=3, assignment="All lights")
    assert list(effect._lamp_channel) == [-2, -2, -2]
    assert list(effect._channel_lamps(2)) == [0, 1, 2]


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


def test_peak_mode_puts_every_lamp_on_the_peak_channel():
    effect = make_effect(pixel_count=3, mode="Peak", light_map="-T-")
    assert list(effect._lamp_channel) == [0, 0, 0]


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
    assert FREQS[masks[3]].max() <= DiscoEffect.VOID_MAX_HZ


def test_narrow_band_falls_back_to_the_nearest_bin():
    effect = make_effect(bass_low=1000, bass_high=1001)
    masks = effect._masks_for(FREQS)
    assert masks[0].sum() == 1


def test_nothing_triggers_before_the_history_holds_music():
    effect = make_effect()
    # The history starts at full scale, a first loud frame is not a hit
    assert not feed(effect, melbank(bass=0.9), 0.0).any()


def test_bass_hit_triggers_only_the_bass_channel():
    effect = make_effect()
    warm_up(effect)
    hits = feed(effect, melbank(bass=0.8), 0.0)
    assert list(hits) == [True, False, False]


def test_hits_need_a_jump_above_the_running_average():
    effect = make_effect()
    # A steady level raises the average until it stops triggering
    hits = feed(effect, melbank(bass=0.3), 0.0, frames=200)
    assert not hits[0]
    # A clear jump above that level is a hit again
    hits = feed(effect, melbank(bass=0.9), 5.0)
    assert hits[0]


def test_hits_are_rate_limited_per_channel():
    effect = make_effect()
    warm_up(effect)
    assert feed(effect, melbank(bass=0.9), 0.0)[0]
    assert not feed(effect, melbank(bass=0.9), 0.05)[0]


def test_a_quieter_hit_waits_for_the_gate_to_decay():
    effect = make_effect(gate_decay=1.0)
    warm_up(effect)
    assert feed(effect, melbank(bass=0.9), 0.0)[0]
    # Half a second of quiet later the gate still sits above a softer hit
    feed(effect, melbank(0.02, 0.02, 0.02), 0.02, frames=24)
    assert not feed(effect, melbank(bass=0.4), 0.5)[0]
    # A second later it has decayed and the softer hit gets through
    feed(effect, melbank(0.02, 0.02, 0.02), 0.52, frames=54)
    assert feed(effect, melbank(bass=0.4), 1.6)[0]


def test_low_sensitivity_needs_more_power():
    quiet = make_effect(sensitivity=0.0)
    loud = make_effect(sensitivity=1.0)
    for effect in (quiet, loud):
        warm_up(effect)
    assert not feed(quiet, melbank(bass=0.06), 0.0)[0]
    assert feed(loud, melbank(bass=0.06), 0.0)[0]


def test_audio_data_updated_reads_the_full_range_melbank():
    effect = make_effect()
    warm_up(effect)
    effect.audio_data_updated(FakeAudio(melbank(treble=0.9)))
    stored = effect._history[2][(effect._hist_idx - 1) % DiscoEffect.HISTORY]
    assert stored == pytest.approx(0.9)


# --------------------------------------------------------------- render


def test_spectrum_hit_lights_the_channel_lamps_only():
    effect = make_effect(pixel_count=6, idle_brightness=0.0)
    warm_up(effect)
    feed(effect, melbank(voice=0.9), 0.0)
    pixels = render_at(effect, 0.0)
    assert lit_lamps(pixels) == [1, 4]
    assert np.array_equal(pixels[1], pixels[4])


def test_a_fade_lasts_the_gap_since_the_previous_hit():
    effect = make_effect(
        pixel_count=3, treble_style="Fade", fade_brightness=0.2, smoothness=0.5
    )
    warm_up(effect)
    feed(effect, melbank(treble=0.9), 0.0)
    feed(effect, melbank(treble=0.9), 1.0)
    # The second hit fades over the 1 s gap, linearly down to 20%
    color = effect._colors[2]
    assert np.allclose(render_at(effect, 1.0)[2], color, atol=1)
    assert np.allclose(render_at(effect, 1.5)[2], color * 0.6, atol=1)
    assert np.allclose(render_at(effect, 1.99)[2], color * 0.208, atol=2)
    # A gap longer than the cap fades over the cap
    feed(effect, melbank(treble=0.9), 5.0)
    assert effect._lamp_fade[2] == pytest.approx(DiscoEffect.FADE_CAP)


def test_smoothness_lengthens_and_shortens_fades():
    longer = make_effect(pixel_count=3, smoothness=1.0)
    shorter = make_effect(pixel_count=3, smoothness=0.0)
    for effect in (longer, shorter):
        warm_up(effect)
        feed(effect, melbank(treble=0.9), 0.0)
        feed(effect, melbank(treble=0.9), 1.0)
    assert longer._lamp_fade[2] == pytest.approx(1.5)
    assert shorter._lamp_fade[2] == pytest.approx(0.5)


def test_hold_style_keeps_full_brightness():
    effect = make_effect(pixel_count=3, voice_style="Hold")
    warm_up(effect)
    feed(effect, melbank(voice=0.9), 0.0)
    assert effect._lamp_fade[1] == np.inf
    assert np.allclose(render_at(effect, 1.5)[1], effect._colors[1], atol=1)


def test_fade_and_pulse_alternates_in_blocks():
    effect = make_effect(pixel_count=3, bass_style="Fade + pulse", pulse_block=4)
    warm_up(effect)
    fades = []
    for i in range(8):
        feed(effect, melbank(bass=0.9), i * 0.5)
        fades.append(effect._lamp_fade[0])
    # The first hit has no previous hit and fades over the cap, the next
    # two are beat length fades, then the block turns over to pulses
    assert fades[0] == pytest.approx(DiscoEffect.FADE_CAP)
    assert all(fade == pytest.approx(0.5) for fade in fades[1:3])
    assert all(fade == pytest.approx(DiscoEffect.PULSE_FADE) for fade in fades[3:7])
    assert fades[7] == pytest.approx(0.5)


def test_plain_fade_never_pulses():
    effect = make_effect(pixel_count=3, bass_style="Fade", pulse_block=2)
    warm_up(effect)
    for i in range(6):
        feed(effect, melbank(bass=0.9), i * 0.5)
    assert not effect._pulse_block[0]
    assert effect._lamp_fade[0] == pytest.approx(0.5)


def test_hit_changes_the_channel_colour():
    effect = make_effect(pixel_count=3)
    warm_up(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    first = np.copy(effect._colors[0])
    feed(effect, melbank(bass=0.9), 1.0)
    assert not np.array_equal(first, effect._colors[0])


def test_intensity_scales_the_output():
    effect = make_effect(pixel_count=3, intensity=0.5, idle_brightness=0.0)
    warm_up(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    assert np.allclose(render_at(effect, 0.0)[0], effect._colors[0] * 0.5, atol=1)


def test_idle_lamps_drift_to_the_idle_brightness():
    effect = make_effect(pixel_count=3, idle_brightness=0.5, gradient=RED_BLUE)
    # No hits since activation at -1 s: idle starts at 1 s and ramps over 2 s
    dark = render_at(effect, 0.5)
    assert dark.max() == 0
    halfway = render_at(effect, 2.0)
    settled = render_at(effect, 2.99)
    assert 0 < halfway.max() < settled.max()
    assert settled.max() == pytest.approx(255 * 0.5, abs=3)
    # Every two seconds a new idle tick starts a new glide
    assert effect._lamp_idle_tick[0] == 0
    render_at(effect, 3.5)
    assert effect._lamp_idle_tick[0] == 1
    assert np.array_equal(effect._lamp_idle_from[0], settled[0])


def test_a_hit_ends_the_idle_drift():
    effect = make_effect(pixel_count=3, idle_brightness=0.5)
    render_at(effect, 2.0)
    assert effect._lamp_idle_tick[0] >= 0
    warm_up(effect, t=-10.0)
    feed(effect, melbank(bass=0.9), 2.1)
    assert effect._lamp_idle_tick[0] == -1
    assert np.allclose(render_at(effect, 2.1)[0], effect._colors[0], atol=1)


def test_peak_mode_flashes_one_random_lamp():
    effect = make_effect(pixel_count=4, mode="Peak", idle_brightness=0.0)
    warm_up(effect)
    feed(effect, melbank(bass=0.9, voice=0.9), 0.0)
    assert len(lit_lamps(render_at(effect, 0.0))) == 1


def test_peak_link_lights_flashes_every_lamp():
    effect = make_effect(
        pixel_count=4, mode="Peak", link_lights=True, idle_brightness=0.0
    )
    warm_up(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    pixels = render_at(effect, 0.0)
    assert lit_lamps(pixels) == [0, 1, 2, 3]
    assert np.all(pixels == pixels[0])


def test_peak_listens_to_the_overall_loudness():
    effect = make_effect(pixel_count=2, mode="Peak")
    warm_up(effect)
    assert feed(effect, melbank(treble=0.9), 0.0)[0]


def test_peak_strobe_flashes_then_goes_dark():
    effect = make_effect(
        pixel_count=2,
        mode="Peak",
        strobe=True,
        strobe_color="#00ff00",
        link_lights=True,
        idle_brightness=0.0,
    )
    warm_up(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    assert np.allclose(render_at(effect, 0.05), [0, 255, 0], atol=1)
    assert render_at(effect, DiscoEffect.STROBE_ON + 0.01).max() == 0


def test_peak_strobe_is_rate_limited():
    effect = make_effect(pixel_count=2, mode="Peak", strobe=True, link_lights=True)
    warm_up(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    effect._history[0][:] = 0.02
    feed(effect, melbank(bass=0.9), 0.15)
    assert effect._last_strobe == 0.0


def test_spectrum_strobe_needs_bass_and_treble_together():
    effect = make_effect(
        pixel_count=3, strobe=True, strobe_color="#00ff00", idle_brightness=0.0
    )
    warm_up(effect)
    feed(effect, melbank(bass=0.9), 0.0)
    assert effect._last_strobe == -np.inf
    effect._history[:] = 0.02
    feed(effect, melbank(bass=0.9, treble=0.9), 1.0)
    assert effect._last_strobe == 1.0
    pixels = render_at(effect, 1.0)
    assert np.allclose(pixels, [0, 255, 0], atol=1)


def test_palette_thirds_keep_each_channel_in_its_third():
    effect = make_effect(pixel_count=3)
    for _ in range(50):
        for channel in range(3):
            point = effect._next_point(effect._points[channel], channel)
            assert channel / 3 <= point < (channel + 1) / 3
            effect._points[channel] = point


def test_whole_palette_lets_channels_roam():
    effect = make_effect(pixel_count=3, channel_colors="Whole palette")
    points = {int(effect._next_point(effect._rng.random(), 0) * 3) for _ in range(60)}
    assert points == {0, 1, 2}


def test_peak_mode_uses_the_whole_palette():
    assert not make_effect(pixel_count=3, mode="Peak").palette_thirds


def test_void_follows_loudness_and_the_loudest_band():
    effect = make_effect(
        pixel_count=3,
        mode="Void",
        modulate_saturation=False,
        gradient=RED_BLUE,
    )
    assert render_at(effect, 0.0).max() == 0
    warm_up(effect)
    feed(effect, melbank(bass=0.6), 0.0, frames=20)
    bassy = render_at(effect, 1.0)
    assert bassy.max() > 0
    assert np.all(bassy == bassy[0])
    assert effect._void_pos < 0.5
    # A brighter passage moves the position up the palette
    feed(effect, melbank(voice=0.6), 2.0, frames=20)
    assert effect._void_pos > 0.5


def test_void_modulates_saturation_with_loudness():
    effect = make_effect(pixel_count=1, mode="Void", gradient=RED_BLUE)
    warm_up(effect, frame=melbank(0.4, 0.4, 0.4))
    feed(effect, melbank(0.15, 0.15, 0.15), 0.0, frames=5)
    quiet = render_at(effect, 0.0)[0]
    feed(effect, melbank(0.9, 0.9, 0.9), 1.0, frames=5)
    loud = render_at(effect, 1.0)[0]
    assert loud.max() > quiet.max()
    # Quiet is pale: the smallest channel is a larger share of the largest
    assert quiet.min() / quiet.max() > loud.min() / loud.max()


def test_config_update_reassigns_lamps():
    effect = make_effect(pixel_count=4)
    effect.update_config({"assignment": "Blocks", "treble": False})
    assert list(effect._lamp_channel) == [0, 0, 1, 1]
