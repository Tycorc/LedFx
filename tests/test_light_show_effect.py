"""Unit tests for the Light Show effect and the shared StepTrigger."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ledfx.effects import Effect
from ledfx.effects.light_show import LightShowEffect
from ledfx.effects.utils.step_trigger import StepTrigger

RED_BLUE = (
    "linear-gradient(90deg, #ff0000 0%, #ff0000 50%, "
    "#0000ff 50%, #0000ff 100%)"
)
RED_WHITE_BLUE = (
    "linear-gradient(90deg, #ff0000 0%, #ff0000 33%, #ffffff 33%, "
    "#ffffff 66%, #0000ff 66%, #0000ff 100%)"
)


def make_effect(pixel_count=5, **config):
    """Build an activated Light Show effect without the audio stack."""
    config.setdefault("trigger", "Timer")
    # 30 BPM: one step every two seconds, so nothing fires mid test
    config.setdefault("timer_bpm", 30)
    effect = LightShowEffect(ledfx=MagicMock(), config=config)
    virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    Effect.activate(effect, virtual)
    effect.now = effect._stepper.last_step_time
    return effect


def render_at(effect, t):
    """Render one frame t seconds after the last step."""
    effect.now = effect._stepper.last_step_time + t
    effect.render()
    return np.copy(effect.pixels)


def step(effect):
    """Force the next step and render at its start."""
    effect._step(effect._stepper.last_step_time + 2.0)
    effect._stepper.last_step_time += 2.0
    return render_at(effect, 0.0)


def lit_lamps(pixels):
    return [int(i) for i in np.flatnonzero(pixels.max(axis=1) > 0)]


class FakeAudio:
    def __init__(self):
        self.bar = 0.0
        self.beat = False
        self.bass = False
        self.onset_now = False
        self.lows = 0.0

    def lows_power(self, filtered=True):
        return self.lows

    def bar_oscillator(self):
        return self.bar

    def bpm_beat_now(self):
        return self.beat

    def volume_beat_now(self):
        return self.bass

    def onset(self):
        return self.onset_now


# ----------------------------------------------------------- StepTrigger


def test_step_trigger_timer_steps_at_the_configured_tempo():
    trigger = StepTrigger(
        {"trigger": "Timer", "steps_per_beat": "1", "timer_bpm": 60}, 0.0
    )
    assert trigger.timer_interval == 1.0
    assert not trigger.poll(0.5)
    assert trigger.poll(1.0)
    assert trigger.step_interval == 1.0
    assert not trigger.poll(1.5)
    assert trigger.poll(2.0)


def test_step_trigger_steps_per_beat_scales_the_timer():
    trigger = StepTrigger(
        {"trigger": "Timer", "steps_per_beat": "2", "timer_bpm": 60}, 0.0
    )
    assert trigger.timer_interval == 0.5


def test_step_trigger_beat_hands_over_from_the_timer():
    trigger = StepTrigger(
        {"trigger": "Beat", "steps_per_beat": "1", "timer_bpm": 60}, 0.0
    )
    assert trigger.using_timer(0.0)
    audio = FakeAudio()
    audio.beat = True
    trigger.audio(audio, 0.1)
    assert not trigger.using_timer(0.1)
    assert trigger.poll(0.1)
    # Within the same beat nothing else fires, and the timer stays out
    audio.beat = False
    audio.bar = 0.5
    trigger.audio(audio, 0.4)
    assert not trigger.poll(0.4)
    # After a long silence the timer takes over again
    assert trigger.using_timer(0.1 + StepTrigger.SILENCE_TIMEOUT + 1)


def test_step_trigger_sub_beat_steps_follow_the_bar_oscillator():
    trigger = StepTrigger(
        {"trigger": "Beat", "steps_per_beat": "2", "timer_bpm": 60}, 0.0
    )
    audio = FakeAudio()
    audio.beat = True
    audio.bar = 0.0
    trigger.audio(audio, 0.0)
    assert trigger.poll(0.0)
    audio.beat = False
    audio.bar = 0.25
    trigger.audio(audio, 0.1)
    assert not trigger.poll(0.1)
    audio.bar = 0.5
    trigger.audio(audio, 0.2)
    assert trigger.poll(0.2)


def test_step_trigger_bass_and_onset_triggers():
    audio = FakeAudio()
    bass = StepTrigger(
        {"trigger": "Bass hit", "steps_per_beat": "1", "timer_bpm": 60},
        0.0,
    )
    audio.bass = True
    bass.audio(audio, 0.0)
    assert bass.poll(0.0)
    onset = StepTrigger(
        {"trigger": "Onset", "steps_per_beat": "1", "timer_bpm": 60}, 0.0
    )
    audio.onset_now = True
    onset.audio(audio, 0.0)
    assert onset.poll(0.0)


def test_step_trigger_progress_runs_from_0_to_1():
    trigger = StepTrigger(
        {"trigger": "Timer", "steps_per_beat": "1", "timer_bpm": 60}, 0.0
    )
    assert trigger.progress(0.0) == 0.0
    assert trigger.progress(0.5) == 0.5
    assert trigger.progress(5.0) == 1.0


# ------------------------------------------------------------ Light Show


def test_pixels_have_the_right_shape_and_range():
    effect = make_effect(pixel_count=5, envelope="hold")
    pixels = render_at(effect, 0.0)
    assert pixels.shape == (5, 3)
    assert pixels.min() >= 0
    assert pixels.max() <= 255
    assert pixels.max() > 0


def test_auto_zones_one_per_pixel_for_bulbs_and_blocks_for_strips():
    assert make_effect(pixel_count=5)._zone_count == 5
    strip = make_effect(pixel_count=300)
    assert strip._zone_count == LightShowEffect.AUTO_ZONE_COUNT
    assert make_effect(pixel_count=3, zones=10)._zone_count == 3


def test_cycle_pattern_walks_the_lamps_in_order():
    effect = make_effect(
        pixel_count=4,
        pattern="cycle",
        envelope="hold",
        backlight_brightness=0.0,
    )
    seen = [lit_lamps(render_at(effect, 0.0))]
    for _ in range(3):
        seen.append(lit_lamps(step(effect)))
    assert all(len(lamps) == 1 for lamps in seen)
    order = [lamps[0] for lamps in seen]
    assert order == [(order[0] + i) % 4 for i in range(4)]


def test_scatter_pattern_never_repeats_the_same_lamp():
    effect = make_effect(
        pixel_count=4,
        pattern="scatter",
        envelope="hold",
        backlight_brightness=0.0,
    )
    previous = lit_lamps(render_at(effect, 0.0))
    for _ in range(20):
        current = lit_lamps(step(effect))
        assert len(current) == 1
        assert current != previous
        previous = current


def test_double_pattern_lights_opposite_lamps():
    effect = make_effect(
        pixel_count=6,
        pattern="double",
        envelope="hold",
        backlight_brightness=0.0,
    )
    lamps = lit_lamps(render_at(effect, 0.0))
    assert len(lamps) == 2
    assert (lamps[1] - lamps[0]) % 6 == 3


def test_stage_pattern_cycles_the_stages():
    effect = make_effect(
        pixel_count=6,
        pattern="stage",
        stages=3,
        envelope="hold",
        backlight_brightness=0.0,
    )
    frames = [lit_lamps(render_at(effect, 0.0))]
    frames += [lit_lamps(step(effect)) for _ in range(2)]
    assert sorted(sum(frames, [])) == [0, 1, 2, 3, 4, 5]
    for lamps in frames:
        assert len(lamps) == 2
        assert lamps[0] % 3 == lamps[1] % 3


def test_fill_pattern_fills_up_then_starts_over():
    effect = make_effect(
        pixel_count=3,
        pattern="fill",
        envelope="hold",
        backlight_brightness=0.0,
    )
    assert lit_lamps(render_at(effect, 0.0)) == [0]
    assert lit_lamps(step(effect)) == [0, 1]
    assert lit_lamps(step(effect)) == [0, 1, 2]
    # Full room: the next step clears and starts again
    assert lit_lamps(step(effect)) == [0]


def test_scatter_fill_uses_every_lamp_once_per_round():
    effect = make_effect(
        pixel_count=4,
        pattern="scatter fill",
        envelope="hold",
        backlight_brightness=0.0,
    )
    lamps = lit_lamps(render_at(effect, 0.0))
    for expected in (2, 3, 4):
        lamps = lit_lamps(step(effect))
        assert len(lamps) == expected
    assert lamps == [0, 1, 2, 3]
    assert len(lit_lamps(step(effect))) == 1


def test_split_pattern_alternates_the_halves():
    effect = make_effect(
        pixel_count=4,
        pattern="split",
        envelope="hold",
        backlight_brightness=0.0,
    )
    first = lit_lamps(render_at(effect, 0.0))
    second = lit_lamps(step(effect))
    assert sorted(first + second) == [0, 1, 2, 3]
    assert first in ([0, 1], [2, 3])


def test_all_pattern_with_strobe_envelope_flashes_every_lamp():
    effect = make_effect(
        pixel_count=5,
        pattern="all",
        envelope="strobe",
        strobe_flashes=2,
        backlight_brightness=0.0,
    )
    assert effect._stepper.step_interval == 2.0
    on = render_at(effect, 0.0)
    off = render_at(effect, 0.5)
    on_again = render_at(effect, 1.0)
    assert lit_lamps(on) == [0, 1, 2, 3, 4]
    assert off.max() == 0
    assert np.array_equal(on, on_again)


def test_fade_grow_and_glow_envelopes():
    fade = make_effect(
        pixel_count=2, pattern="all", envelope="fade", backlight_brightness=0
    )
    assert np.allclose(render_at(fade, 1.0), render_at(fade, 0.0) * 0.5)
    grow = make_effect(
        pixel_count=2, pattern="all", envelope="grow", backlight_brightness=0
    )
    assert render_at(grow, 0.0).max() == 0
    assert np.allclose(
        render_at(grow, 1.0), render_at(grow, 1.99) * 0.5, atol=3
    )
    glow = make_effect(
        pixel_count=2, pattern="all", envelope="glow", backlight_brightness=0
    )
    assert render_at(glow, 0.0).max() == 0
    assert render_at(glow, 1.0).max() > render_at(glow, 0.5).max() > 0
    assert render_at(glow, 1.99).max() < 10


def test_flare_starts_from_the_flare_colour():
    effect = make_effect(
        pixel_count=2,
        pattern="all",
        envelope="flare",
        flare_color="#00ff00",
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    assert np.all(render_at(effect, 0.0) == [0, 255, 0])
    later = render_at(effect, 1.0)
    assert later[0][1] == 0  # no green left once the flare has settled


def test_backlight_lights_the_unlit_lamps():
    effect = make_effect(
        pixel_count=3,
        pattern="cycle",
        envelope="hold",
        backlight="#0000ff",
        backlight_brightness=0.5,
        gradient=RED_BLUE,
    )
    pixels = render_at(effect, 0.0)
    unlit = [i for i in range(3) if i != effect._cursor]
    for lamp in unlit:
        assert np.allclose(pixels[lamp], [0, 0, 127.5])


def test_cycle_colours_step_through_a_palette():
    effect = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="hold",
        color_mode="cycle",
        color_step=1 / 3,
        gradient=RED_WHITE_BLUE,
        backlight_brightness=0,
    )
    seen = {tuple(render_at(effect, 0.0)[0])}
    for _ in range(2):
        seen.add(tuple(step(effect)[0]))
    assert seen == {(255, 0, 0), (255, 255, 255), (0, 0, 255)}


def test_zero_colour_step_keeps_one_colour():
    effect = make_effect(
        pixel_count=2,
        pattern="all",
        envelope="hold",
        color_mode="cycle",
        color_step=0.0,
        backlight_brightness=0,
    )
    first = render_at(effect, 0.0)
    assert np.array_equal(first, step(effect))


def test_random_colours_change_every_lit_lamp():
    effect = make_effect(
        pixel_count=4,
        pattern="all",
        envelope="hold",
        color_mode="random",
        backlight_brightness=0,
    )
    before = render_at(effect, 0.0)
    after = step(effect)
    assert np.any(before != after, axis=1).all()


def test_per_lamp_colours_spread_the_palette_over_the_room():
    effect = make_effect(
        pixel_count=2,
        pattern="all",
        envelope="hold",
        color_mode="per lamp",
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    pixels = render_at(effect, 0.0)
    assert np.all(pixels[0] == [255, 0, 0])
    assert np.all(pixels[1] == [0, 0, 255])


def test_loop_pattern_rotates_the_palette_along_the_lamps():
    effect = make_effect(
        pixel_count=4,
        pattern="loop",
        envelope="hold",
        color_mode="per lamp",
        stages=1,
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    before = render_at(effect, 0.0)
    after = step(effect)
    # Every lamp took the colour of its neighbour
    assert np.array_equal(after[:-1], before[1:])


def test_wave_pattern_moves_a_brightness_wave():
    effect = make_effect(
        pixel_count=8,
        pattern="wave",
        envelope="hold",
        color_mode="cycle",
        stages=1,
        backlight_brightness=0,
    )
    start = render_at(effect, 0.0).max(axis=1)
    half = render_at(effect, 1.0).max(axis=1)
    assert start.max() > 0
    assert not np.allclose(start, half)
    # Half a step later the wave has moved half a turn: peaks became troughs
    assert np.argmax(start) != np.argmax(half)


def test_config_update_keeps_working_and_reapplies_settings():
    effect = make_effect(pixel_count=4, pattern="cycle", envelope="hold")
    effect.update_config({"pattern": "all", "envelope": "strobe", "stages": 2})
    assert effect.pattern == "all"
    assert effect.strobe_flashes == 1
    step(effect)
    assert lit_lamps(render_at(effect, 0.0)) == [0, 1, 2, 3]


@pytest.mark.parametrize("pattern", LightShowEffect.PATTERNS)
@pytest.mark.parametrize("envelope", LightShowEffect.ENVELOPES)
def test_every_pattern_and_envelope_renders_on_one_lamp(pattern, envelope):
    effect = make_effect(pixel_count=1, pattern=pattern, envelope=envelope)
    for _ in range(3):
        pixels = step(effect)
        assert pixels.shape == (1, 3)
        assert 0 <= pixels.min() and pixels.max() <= 255
        render_at(effect, 0.7)


def test_config_update_keeps_the_lit_lamps_when_the_lamp_count_is_unchanged():
    effect = make_effect(
        pixel_count=4, pattern="cycle", envelope="hold", backlight_brightness=0
    )
    lit = lit_lamps(render_at(effect, 0.0))
    effect.update_config({"envelope": "fade"})
    assert lit_lamps(render_at(effect, 0.0)) == lit
    effect.update_config({"zones": 2})
    assert effect._zone_count == 2
    assert len(effect._lit_now) == 2


# -------------------------------------------------------------- auto mode


def test_auto_settings_resolve_to_concrete_values():
    effect = make_effect(
        pixel_count=4, pattern="auto", envelope="auto", color_mode="auto"
    )
    assert effect.on_auto
    assert effect.pattern in LightShowEffect.AUTO_QUIET_PATTERNS
    assert effect.envelope in LightShowEffect.AUTO_QUIET_ENVELOPES
    assert effect.color_mode in LightShowEffect.AUTO_COLOR_MODES
    for _ in range(3):
        pixels = step(effect)
        assert pixels.shape == (4, 3)


def test_auto_changes_every_auto_steps():
    effect = make_effect(
        pixel_count=4,
        pattern="auto",
        envelope="auto",
        color_mode="auto",
        auto_steps=4,
    )
    before = (effect.pattern, effect.envelope, effect.color_mode)
    # The first step already ran at activation, three more stay put
    for _ in range(2):
        step(effect)
        assert (effect.pattern, effect.envelope, effect.color_mode) == before
    step(effect)
    after = (effect.pattern, effect.envelope, effect.color_mode)
    assert after != before
    assert after[0] != before[0]
    assert after[1] != before[1]
    assert after[2] != before[2]


def test_auto_picks_the_loud_set_on_loud_music():
    effect = make_effect(
        pixel_count=4, pattern="auto", envelope="auto", auto_steps=1
    )
    audio = FakeAudio()
    audio.lows = 1.0
    for _ in range(100):
        effect.audio_data_updated(audio)
    assert effect._energy >= LightShowEffect.AUTO_LOUD_LEVEL
    picks = set()
    for _ in range(30):
        step(effect)
        assert effect.pattern in LightShowEffect.AUTO_LOUD_PATTERNS
        assert effect.envelope in LightShowEffect.AUTO_LOUD_ENVELOPES
        picks.add(effect.pattern)
    assert len(picks) > 1


def test_fixed_settings_are_left_alone_by_auto():
    effect = make_effect(
        pixel_count=4,
        pattern="cycle",
        envelope="auto",
        color_mode="per lamp",
        auto_steps=1,
    )
    for _ in range(5):
        step(effect)
        assert effect.pattern == "cycle"
        assert effect.color_mode == "per lamp"
        assert effect.envelope != "auto"


def test_without_auto_no_energy_is_tracked():
    effect = make_effect(pixel_count=4, pattern="cycle")
    assert not effect.on_auto
    audio = FakeAudio()
    audio.lows = 1.0
    effect.audio_data_updated(audio)
    assert effect._energy == 0.0
