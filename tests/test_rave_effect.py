"""Unit tests for the Rave (party mode) effect."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ledfx.effects import Effect
from ledfx.effects.rave import RaveEffect

RED_BLUE = (
    "linear-gradient(90deg, #ff0000 0%, #ff0000 50%, "
    "#0000ff 50%, #0000ff 100%)"
)


def make_effect(pixel_count=5, **config):
    """Build an activated Rave effect without touching the audio stack."""
    effect = RaveEffect(ledfx=MagicMock(), config=config)
    virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    # Effect.activate runs the on_activate hooks but skips the audio
    # subscription that AudioReactiveEffect.activate would set up.
    Effect.activate(effect, virtual)
    effect.now = effect._last_step_time
    return effect


def render_at(effect, t):
    """Render one frame as if the clock read t seconds after activation."""
    effect.now = effect._last_step_time + t
    effect.render()
    return np.copy(effect.pixels)


class FakeAudio:
    """Minimal stand in for AudioAnalysisSource."""

    def __init__(self):
        self.bar = 0.0
        self.beat = False
        self.bass = False
        self.onset_now = False

    def bar_oscillator(self):
        return self.bar

    def bpm_beat_now(self):
        return self.beat

    def volume_beat_now(self):
        return self.bass

    def onset(self):
        return self.onset_now


def test_auto_zones_one_per_pixel_for_bulbs():
    effect = make_effect(pixel_count=5)
    assert effect._zone_count == 5
    assert list(effect._zone_of_pixel) == [0, 1, 2, 3, 4]


def test_auto_zones_splits_long_strips():
    effect = make_effect(pixel_count=300)
    assert effect._zone_count == RaveEffect.AUTO_ZONE_COUNT
    # Zones are contiguous, ordered blocks of roughly equal size
    zone_of_pixel = effect._zone_of_pixel
    assert zone_of_pixel[0] == 0
    assert zone_of_pixel[-1] == RaveEffect.AUTO_ZONE_COUNT - 1
    assert np.all(np.diff(zone_of_pixel) >= 0)


def test_explicit_zones_are_clamped_to_pixel_count():
    effect = make_effect(pixel_count=3, zones=10)
    assert effect._zone_count == 3


def test_pixels_have_the_right_shape_and_range():
    effect = make_effect(pixel_count=5)
    pixels = render_at(effect, 0.0)
    assert pixels.shape == (5, 3)
    assert pixels.min() >= 0
    assert pixels.max() <= 255
    # Something is lit straight after activation
    assert pixels.max() > 0


def test_random_mode_changes_every_lamp_on_a_step():
    effect = make_effect(pixel_count=5, trigger="Timer", timer_bpm=120)
    before = render_at(effect, 0.0)
    # Just under one timer interval: no step yet
    same = render_at(effect, effect.timer_interval * 0.9)
    assert np.array_equal(before, same)
    # Past the interval: every lamp got a new colour
    after = render_at(effect, effect.timer_interval * 1.01)
    changed = np.any(before != after, axis=1)
    assert changed.all()


def test_wash_mode_lights_all_lamps_the_same():
    effect = make_effect(pixel_count=6, mode="wash", trigger="Timer")
    for t in (0.0, 1.0, 2.0):
        pixels = render_at(effect, t)
        assert np.all(pixels == pixels[0])
        assert pixels.max() > 0


def test_chase_mode_lights_one_lamp_and_advances():
    effect = make_effect(pixel_count=4, mode="chase", trigger="Timer")
    lit = []
    for _ in range(4):
        effect._step(effect._last_step_time + 1.0)
        pixels = render_at(effect, 0.0)
        lit_lamps = np.flatnonzero(pixels.max(axis=1) > 0)
        assert len(lit_lamps) == 1
        lit.append(int(lit_lamps[0]))
    assert lit == [1, 2, 3, 0] or sorted(lit) == [0, 1, 2, 3]


def test_alternate_mode_swaps_even_and_odd_lamps():
    effect = make_effect(
        pixel_count=4, mode="alternate", trigger="Timer", gradient=RED_BLUE
    )
    # Every pair of colours is shown for two steps: as is, then swapped
    for _ in range(3):
        first = render_at(effect, 0.0)
        assert np.array_equal(first[0], first[2])
        assert np.array_equal(first[1], first[3])
        assert not np.array_equal(first[0], first[1])

        effect._step(effect._last_step_time + 1.0)
        second = render_at(effect, 0.0)
        assert np.array_equal(second[0], first[1])
        assert np.array_equal(second[1], first[0])

        effect._step(effect._last_step_time + 1.0)


def test_alternate_mode_never_shows_one_colour_on_a_hard_edged_palette():
    effect = make_effect(
        pixel_count=2, mode="alternate", trigger="Timer", gradient=RED_BLUE
    )
    # Force the pair point into the window where both points would land on
    # the red side of the palette stop
    effect._pair_point = 0.0
    effect._alt_phase = 1
    effect._step(effect._last_step_time + 1.0)
    pixels = render_at(effect, 0.0)
    assert not np.array_equal(pixels[0], pixels[1])


def test_fade_dims_lamps_between_steps():
    # 30 BPM: one timer step every 2 seconds, so nothing fires mid test
    effect = make_effect(
        pixel_count=5, trigger="Timer", timer_bpm=30, fade=1.0
    )
    assert effect._step_interval == 2.0
    bright = render_at(effect, 0.0)
    dim = render_at(effect, 1.0)
    dark = render_at(effect, 1.99)
    assert bright.max() > dim.max() > dark.max()
    assert np.allclose(dim, bright * 0.5)


def test_strobe_mode_flashes_the_strobe_colour():
    effect = make_effect(
        pixel_count=5,
        mode="strobe",
        trigger="Timer",
        timer_bpm=30,
        strobe_flashes=2,
        strobe_color="#00ff00",
    )
    # Two flashes in a 2 second step: on at 0 and 1, off in between
    assert effect._step_interval == 2.0
    on = render_at(effect, 0.0)
    off = render_at(effect, 0.5)
    on_again = render_at(effect, 1.0)
    assert np.all(on == [0, 255, 0])
    assert off.max() == 0
    assert np.all(on_again == [0, 255, 0])


def test_beat_trigger_steps_once_per_beat():
    effect = make_effect(pixel_count=5, trigger="Beat", steps_per_beat="1")
    audio = FakeAudio()

    # First beat: audio takes control and a step is queued
    audio.beat = True
    audio.bar = 0.0
    effect.audio_data_updated(audio)
    assert effect._step_pending
    effect._step_pending = False

    # Moving within the same beat does not queue another step
    audio.beat = False
    audio.bar = 0.5
    effect.audio_data_updated(audio)
    assert not effect._step_pending

    # Crossing into the next beat does
    audio.bar = 1.1
    effect.audio_data_updated(audio)
    assert effect._step_pending
    effect._step_pending = False

    # Wrapping around the bar counts as a new beat too
    audio.bar = 3.9
    effect.audio_data_updated(audio)
    effect._step_pending = False
    audio.bar = 0.1
    effect.audio_data_updated(audio)
    assert effect._step_pending


def test_beat_trigger_sub_steps():
    effect = make_effect(pixel_count=5, trigger="Beat", steps_per_beat="4")
    audio = FakeAudio()
    audio.beat = True
    effect.audio_data_updated(audio)
    effect._step_pending = False
    audio.beat = False

    steps = 0
    for bar in np.linspace(0.01, 0.99, 40):
        audio.bar = bar
        effect.audio_data_updated(audio)
        if effect._step_pending:
            steps += 1
            effect._step_pending = False
    # Quarter beat boundaries at 0.25, 0.5 and 0.75
    assert steps == 3


def test_timer_takes_over_when_no_beat_is_heard():
    effect = make_effect(pixel_count=5, trigger="Beat", timer_bpm=120)
    audio = FakeAudio()

    # A beat hands control to the audio trigger: the timer must stay quiet
    audio.beat = True
    effect.audio_data_updated(audio)
    effect._step_pending = False
    before = render_at(effect, effect.timer_interval * 2)
    assert np.array_equal(before, render_at(effect, effect.timer_interval * 2))

    # Long silence: the timer resumes stepping at timer_bpm
    effect._last_audio_trigger -= RaveEffect.SILENCE_TIMEOUT + 1
    after = render_at(effect, effect.timer_interval * 2)
    assert not np.array_equal(before, after)

    # And while silent, the free running bar oscillator is ignored
    audio.beat = False
    audio.bar = 2.0
    effect.audio_data_updated(audio)
    assert not effect._step_pending


@pytest.mark.parametrize("trigger", ["Bass hit", "Onset"])
def test_hit_triggers_queue_a_step(trigger):
    effect = make_effect(pixel_count=5, trigger=trigger)
    audio = FakeAudio()
    effect.audio_data_updated(audio)
    assert not effect._step_pending
    audio.bass = True
    audio.onset_now = True
    effect.audio_data_updated(audio)
    assert effect._step_pending


def test_config_update_rebuilds_zones_and_keeps_colours():
    effect = make_effect(pixel_count=8, zones=4)
    assert effect._zone_count == 4
    old_colors = np.copy(effect._zone_colors)
    effect.update_config({"zones": 8})
    assert effect._zone_count == 8
    assert np.array_equal(effect._zone_colors[:4], old_colors)
    effect.update_config({"zones": 2})
    assert effect._zone_count == 2
    assert np.array_equal(effect._zone_colors, old_colors[:2])
