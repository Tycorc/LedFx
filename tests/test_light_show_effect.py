"""Unit tests for the Light Show effect and the shared StepTrigger."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ledfx.effects import Effect
from ledfx.effects.light_show import LightShowEffect
from ledfx.effects.utils.step_trigger import StepTrigger

RED_BLUE = "linear-gradient(90deg, #ff0000 0%, #ff0000 50%, #0000ff 50%, #0000ff 100%)"
RED_WHITE_BLUE = (
    "linear-gradient(90deg, #ff0000 0%, #ff0000 33%, #ffffff 33%, "
    "#ffffff 66%, #0000ff 66%, #0000ff 100%)"
)


SEED = 7


def activate(effect, virtual, seed=SEED):
    """Activate with a seeded random generator so runs are reproducible."""
    default_rng = np.random.default_rng
    with patch("numpy.random.default_rng", lambda: default_rng(seed)):
        Effect.activate(effect, virtual)


def make_effect(pixel_count=5, seed=SEED, **config):
    """Build an activated Light Show effect without the audio stack."""
    config.setdefault("trigger", "Timer")
    # 30 BPM: one step every two seconds, so nothing fires mid test
    config.setdefault("timer_bpm", 30)
    effect = LightShowEffect(ledfx=MagicMock(), config=config)
    virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    activate(effect, virtual, seed)
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
    assert sorted(lamp for frame in frames for lamp in frame) == [0, 1, 2, 3, 4, 5]
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
    assert np.allclose(render_at(grow, 1.0), render_at(grow, 1.99) * 0.5, atol=3)
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
    effect = make_effect(pixel_count=4, pattern="auto", envelope="auto", auto_steps=1)
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


# ------------------------------------------------------ room harness

RED = "linear-gradient(90deg, #ff0000 0%, #ff0000 100%)"

# Four lamps in the corners of a room: front left, front right, back
# right, back left (clockwise from the front left)
CORNERS = [
    [-1.0, 1.0, 0.0],
    [1.0, 1.0, 0.0],
    [1.0, -1.0, 0.0],
    [-1.0, -1.0, 0.0],
]
# The same corners in a scrambled light order: back right, front left,
# back left, front right. Clockwise from the front that is 3, 0, 2, 1.
SCRAMBLED = [CORNERS[2], CORNERS[0], CORNERS[3], CORNERS[1]]
SCRAMBLED_WALK = [3, 0, 2, 1]


def make_room_effect(positions, **config):
    """A Light Show on a fake device that knows where its lamps are."""
    config.setdefault("grouping", "room")
    config.setdefault("trigger", "Timer")
    config.setdefault("timer_bpm", 30)
    count = len(positions)
    device = SimpleNamespace(
        pixel_positions=[list(p) for p in positions], pixel_count=count
    )
    ledfx = MagicMock()
    ledfx.devices.get.return_value = device
    effect = LightShowEffect(ledfx=ledfx, config=config)
    virtual = SimpleNamespace(
        effective_pixel_count=count,
        id="test",
        _segments=[["hue", 0, count - 1, False]],
        _config={"mapping": "span"},
        group_size=1,
        rows=1,
    )
    activate(effect, virtual)
    effect.now = effect._stepper.last_step_time
    return effect


def bright(pixels):
    return pixels.max(axis=1)


# --------------------------------------------------------- new patterns


def test_flip_pattern_alternates_even_and_odd_lamps():
    effect = make_effect(
        pixel_count=4, pattern="flip", envelope="hold", backlight_brightness=0
    )
    first = lit_lamps(render_at(effect, 0.0))
    second = lit_lamps(step(effect))
    assert first in ([0, 2], [1, 3])
    assert sorted(first + second) == [0, 1, 2, 3]
    assert lit_lamps(step(effect)) == first


def test_sprinkle_lights_stages_lamps_and_changes_the_set():
    effect = make_effect(
        pixel_count=8,
        pattern="sprinkle",
        stages=3,
        envelope="hold",
        backlight_brightness=0,
    )
    previous = lit_lamps(render_at(effect, 0.0))
    assert len(previous) == 3
    for _ in range(20):
        current = lit_lamps(step(effect))
        assert len(current) == 3
        assert current != previous
        previous = current


def test_stage_fill_accumulates_the_groups_then_clears():
    effect = make_effect(
        pixel_count=6,
        pattern="stage fill",
        stages=3,
        envelope="hold",
        backlight_brightness=0,
    )
    assert lit_lamps(render_at(effect, 0.0)) == [0, 3]
    assert lit_lamps(step(effect)) == [0, 1, 3, 4]
    assert lit_lamps(step(effect)) == [0, 1, 2, 3, 4, 5]
    assert lit_lamps(step(effect)) == [0, 3]


def test_paint_paints_over_the_old_colour_group_by_group():
    effect = make_effect(
        pixel_count=4,
        pattern="paint",
        stages=2,
        envelope="hold",
        color_mode="cycle",
        color_step=0.5,
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    first = render_at(effect, 0.0)
    assert lit_lamps(first) == [0, 2]
    colour = tuple(first[0])
    other = (0, 0, 255) if colour == (255, 0, 0) else (255, 0, 0)
    full = step(effect)
    assert lit_lamps(full) == [0, 1, 2, 3]
    assert all(tuple(full[i]) == colour for i in range(4))
    # The next round paints the other colour over the first group only
    repaint = step(effect)
    assert tuple(repaint[0]) == other and tuple(repaint[2]) == other
    assert tuple(repaint[1]) == colour and tuple(repaint[3]) == colour
    done = step(effect)
    assert all(tuple(done[i]) == other for i in range(4))


def test_paint_shows_the_backlight_until_a_lamp_is_painted():
    effect = make_effect(
        pixel_count=4,
        pattern="paint",
        stages=2,
        envelope="hold",
        backlight="#0000ff",
        backlight_brightness=0.5,
        gradient=RED,
    )
    pixels = render_at(effect, 0.0)
    assert np.allclose(pixels[1], [0, 0, 127.5])
    assert np.allclose(pixels[0], [255, 0, 0])


def test_scatter_paint_covers_every_group_each_round():
    effect = make_effect(
        pixel_count=6,
        pattern="scatter paint",
        stages=3,
        envelope="hold",
        backlight_brightness=0,
    )
    assert len(lit_lamps(render_at(effect, 0.0))) == 2
    assert len(lit_lamps(step(effect))) == 4
    assert lit_lamps(step(effect)) == [0, 1, 2, 3, 4, 5]
    # Painted lamps stay lit while the next round paints over them
    assert lit_lamps(step(effect)) == [0, 1, 2, 3, 4, 5]


def test_sweep_fills_the_groups_then_drains_them_in_order():
    effect = make_effect(
        pixel_count=4,
        pattern="sweep",
        stages=2,
        envelope="hold",
        backlight_brightness=0,
    )
    assert lit_lamps(render_at(effect, 0.0)) == [0, 2]
    assert lit_lamps(step(effect)) == [0, 1, 2, 3]
    assert lit_lamps(step(effect)) == [1, 3]
    assert lit_lamps(step(effect)) == []
    assert lit_lamps(step(effect)) == [0, 2]


def test_rest_steps_keep_the_room_dark_after_a_round():
    effect = make_effect(
        pixel_count=4,
        pattern="sweep",
        stages=2,
        rest_steps=2,
        envelope="hold",
        backlight_brightness=0,
    )
    seen = [lit_lamps(render_at(effect, 0.0))]
    seen += [lit_lamps(step(effect)) for _ in range(6)]
    assert seen == [[0, 2], [0, 1, 2, 3], [1, 3], [], [], [], [0, 2]]


def test_chase_moves_a_block_of_lamps_along_the_walk():
    effect = make_effect(
        pixel_count=6,
        pattern="chase",
        stages=2,
        envelope="hold",
        backlight_brightness=0,
    )
    first = lit_lamps(render_at(effect, 0.0))
    second = lit_lamps(step(effect))
    assert len(first) == 2 and len(second) == 2
    assert (first[1] - first[0]) % 6 in (1, 5)
    assert sorted(set(first + second)) != first
    assert set(first) & set(second)


def test_chase_carries_the_palette_in_its_block():
    effect = make_effect(
        pixel_count=6,
        pattern="chase",
        stages=2,
        envelope="hold",
        color_mode="per lamp",
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    pixels = step(effect)
    block = list(effect._chase_block)
    assert np.array_equal(pixels[block[0]], [255, 0, 0])
    assert np.array_equal(pixels[block[1]], [0, 0, 255])


def test_ramp_steps_the_brightness_of_one_group_at_a_time():
    effect = make_effect(
        pixel_count=4,
        pattern="ramp",
        stages=4,
        envelope="hold",
        gradient=RED,
        backlight_brightness=0,
    )
    levels = [bright(render_at(effect, 0.0))[0]]
    levels += [bright(step(effect))[0] for _ in range(3)]
    assert np.allclose(levels, [0.0, 63.75, 127.5, 191.25])
    after = step(effect)
    assert bright(after)[0] == 0 and bright(after)[1] == 0


# -------------------------------------------------------- new envelopes


def test_dip_keeps_the_room_on_and_dips_the_lit_lamp_out():
    effect = make_effect(
        pixel_count=3,
        pattern="cycle",
        envelope="dip",
        color_step=0.0,
        gradient=RED,
        backlight_brightness=0,
    )
    start = render_at(effect, 0.0)
    assert np.all(start == [255, 0, 0])
    half = render_at(effect, 1.0)
    lamp = effect._cursor
    assert np.allclose(half[effect._walk[lamp]], [127.5, 0, 0])
    others = [i for i in range(3) if i != effect._walk[lamp]]
    assert np.all(half[others] == [255, 0, 0])


def test_peak_envelope_rises_flashes_the_peak_colour_and_falls():
    effect = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="peak",
        flare_color="#ffffff",
        gradient=RED,
        backlight_brightness=0,
    )
    assert bright(render_at(effect, 0.0))[0] == 0
    rising = render_at(effect, 0.4)[0]
    assert np.allclose(rising, [255 * 0.2 / 0.45, 0, 0])
    assert np.all(render_at(effect, 0.95)[0] == [255, 255, 255])
    falling = render_at(effect, 1.6)[0]
    assert np.allclose(falling, [255 * 0.2 / 0.45, 0, 0])
    assert bright(render_at(effect, 1.99))[0] < 10


def test_pulse_envelope_gives_strobe_flashes_pulses_per_step():
    effect = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="pulse",
        strobe_flashes=3,
        gradient=RED,
        backlight_brightness=0,
    )
    on = [0.1, 0.55, 1.05]
    off = [0.3, 0.8, 1.3, 1.6, 1.9]
    for t in on:
        assert bright(render_at(effect, t))[0] == 255
    for t in off:
        assert bright(render_at(effect, t))[0] == 0


def test_cross_fade_blends_from_the_old_colour_over_the_step():
    effect = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="cross fade",
        color_mode="cycle",
        color_step=0.5,
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    # At the start of a step the lamp still shows the previous colour
    old = np.copy(step(effect)[0])
    assert tuple(old) in ((255, 0, 0), (0, 0, 255))
    middle = render_at(effect, 1.0)[0]
    assert np.allclose(middle, [127.5, 0, 127.5])
    new = render_at(effect, 1.99)[0]
    assert np.argmax(new) != np.argmax(old)
    assert new.max() > 250


def test_swell_envelope_follows_a_slow_sine_over_the_steps():
    effect = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="swell",
        gradient=RED,
        backlight_brightness=0,
    )
    first = bright(render_at(effect, 0.0))[0]
    assert np.isclose(first, 255 * (0.5 + 0.5 * np.sin(np.radians(11.25))))
    while effect._step_count < 8:
        pixels = step(effect)
    assert bright(pixels)[0] == 255
    while effect._step_count < 24:
        pixels = step(effect)
    assert bright(pixels)[0] < 1


# -------------------------------------------- trail, rhythm and flashes


def test_trail_overlaps_the_fades_of_successive_lamps():
    effect = make_effect(
        pixel_count=4,
        pattern="cycle",
        envelope="fade",
        trail=2,
        gradient=RED,
        backlight_brightness=0,
    )
    step(effect)
    pixels = step(effect)
    levels = bright(pixels)
    assert sorted(levels.tolist()) == [0.0, 0.0, 127.5, 255.0]
    # Half a step later both fades have moved on
    later = bright(render_at(effect, 1.0))
    assert sorted(later.tolist()) == [0.0, 0.0, 63.75, 191.25]


def test_trail_keeps_the_earlier_lamps_on_with_hold():
    effect = make_effect(
        pixel_count=5,
        pattern="cycle",
        envelope="hold",
        trail=3,
        backlight_brightness=0,
    )
    assert len(lit_lamps(render_at(effect, 0.0))) == 1
    assert len(lit_lamps(step(effect))) == 2
    assert len(lit_lamps(step(effect))) == 3
    assert len(lit_lamps(step(effect))) == 3


def test_rhythm_chop_holds_and_blanks_the_lamps():
    effect = make_effect(
        pixel_count=4,
        pattern="cycle",
        envelope="hold",
        rhythm="chop",
        backlight_brightness=0,
    )
    first = lit_lamps(render_at(effect, 0.0))
    assert len(first) == 1
    assert lit_lamps(step(effect)) == first  # "." keeps the lamp
    assert lit_lamps(step(effect)) == []  # "o" turns everything off
    assert lit_lamps(step(effect)) == []
    following = lit_lamps(step(effect))  # the next "x" moves on
    assert len(following) == 1 and following != first


def test_rhythm_gap_stretches_the_envelope_to_the_next_hit():
    effect = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="fade",
        rhythm="downbeat",
        gradient=RED,
        backlight_brightness=0,
    )
    # Hits are four steps apart, so the fade takes four steps
    assert np.isclose(bright(render_at(effect, 1.99))[0], 255 * (1 - 1.99 / 8))
    step(effect)
    assert np.isclose(bright(render_at(effect, 0.0))[0], 255 * 0.75)
    step(effect)
    assert np.isclose(bright(render_at(effect, 0.0))[0], 255 * 0.5)
    step(effect)
    assert np.isclose(bright(render_at(effect, 0.0))[0], 255 * 0.25)
    # The next hit lights the lamp again
    assert bright(step(effect))[0] == 255


def test_flash_length_lengthens_the_strobe_flash():
    short = make_effect(
        pixel_count=1, pattern="all", envelope="strobe", backlight_brightness=0
    )
    assert bright(render_at(short, 0.2))[0] == 0
    long = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="strobe",
        flash_length=0.3,
        backlight_brightness=0,
    )
    assert bright(render_at(long, 0.2))[0] > 0
    assert bright(render_at(long, 0.4))[0] == 0


def test_flash_limit_blocks_rises_that_come_too_fast():
    limited = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="strobe",
        strobe_flashes=8,
        backlight_brightness=0,
    )
    assert bright(render_at(limited, 0.0))[0] > 0
    assert bright(render_at(limited, 0.1))[0] == 0
    assert bright(render_at(limited, 0.25))[0] == 0
    assert bright(render_at(limited, 0.4))[0] == 0
    assert bright(render_at(limited, 0.5))[0] > 0
    free = make_effect(
        pixel_count=1,
        pattern="all",
        envelope="strobe",
        strobe_flashes=8,
        flash_limit=False,
        backlight_brightness=0,
    )
    assert bright(render_at(free, 0.0))[0] > 0
    assert bright(render_at(free, 0.1))[0] == 0
    assert bright(render_at(free, 0.25))[0] > 0


# ----------------------------------------------------- per group colours


def test_per_group_colours_rotate_between_the_groups():
    effect = make_effect(
        pixel_count=4,
        pattern="all",
        envelope="hold",
        color_mode="per group",
        stages=2,
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    first = render_at(effect, 0.0)
    assert np.array_equal(first[0], first[2])
    assert np.array_equal(first[1], first[3])
    assert not np.array_equal(first[0], first[1])
    second = step(effect)
    assert np.array_equal(second[0], first[1])
    assert np.array_equal(second[1], first[0])


def test_per_group_on_four_corners_turns_a_two_colour_split():
    effect = make_room_effect(
        CORNERS,
        pattern="all",
        envelope="hold",
        color_mode="per group",
        stages=4,
        gradient=RED_BLUE,
        backlight_brightness=0,
    )

    def red_lamps(pixels):
        return sorted(int(i) for i in np.flatnonzero(pixels[:, 0] > 0))

    halves = [red_lamps(render_at(effect, 0.0))]
    halves += [red_lamps(step(effect)) for _ in range(3)]
    # front, left, back, right: the divide turns a quarter every step
    assert halves == [[0, 1], [0, 3], [2, 3], [1, 2]]


# ---------------------------------------------------------- room grouping


def test_room_stage_with_two_groups_is_front_and_back():
    effect = make_room_effect(
        CORNERS,
        pattern="stage",
        stages=2,
        envelope="hold",
        backlight_brightness=0,
    )
    first = lit_lamps(render_at(effect, 0.0))
    second = lit_lamps(step(effect))
    assert sorted([first, second]) == [[0, 1], [2, 3]]


def test_room_stage_with_four_groups_takes_the_corners_in_turn():
    effect = make_room_effect(
        CORNERS,
        pattern="stage",
        stages=4,
        envelope="hold",
        backlight_brightness=0,
    )
    seen = [lit_lamps(render_at(effect, 0.0))]
    seen += [lit_lamps(step(effect)) for _ in range(3)]
    assert all(len(lamps) == 1 for lamps in seen)
    assert sorted(lamp for frame in seen for lamp in frame) == [0, 1, 2, 3]


def test_room_split_is_left_and_right():
    effect = make_room_effect(
        CORNERS, pattern="split", envelope="hold", backlight_brightness=0
    )
    first = lit_lamps(render_at(effect, 0.0))
    second = lit_lamps(step(effect))
    assert sorted([first, second]) == [[0, 3], [1, 2]]


def test_room_double_lights_diagonal_corners():
    effect = make_room_effect(
        CORNERS, pattern="double", envelope="hold", backlight_brightness=0
    )
    lamps = lit_lamps(render_at(effect, 0.0))
    assert lamps in ([0, 2], [1, 3])


def test_room_double_lights_opposite_sides_of_a_ring():
    effect = make_effect(
        pixel_count=8,
        pattern="double",
        grouping="room",
        layout="Ring",
        envelope="hold",
        backlight_brightness=0,
    )
    for _ in range(4):
        lamps = lit_lamps(step(effect))
        assert len(lamps) == 2
        assert (lamps[1] - lamps[0]) % 8 == 4


def test_room_cycle_walks_clockwise_by_angle():
    effect = make_room_effect(
        SCRAMBLED, pattern="cycle", envelope="hold", backlight_brightness=0
    )
    assert effect._walk.tolist() == SCRAMBLED_WALK
    seen = [lit_lamps(render_at(effect, 0.0))[0]]
    seen += [lit_lamps(step(effect))[0] for _ in range(3)]
    start = SCRAMBLED_WALK.index(seen[0])
    assert seen == [SCRAMBLED_WALK[(start + i) % 4] for i in range(4)]


def test_room_fill_runs_around_the_room():
    effect = make_room_effect(
        SCRAMBLED, pattern="fill", envelope="hold", backlight_brightness=0
    )
    assert lit_lamps(render_at(effect, 0.0)) == [3]
    assert lit_lamps(step(effect)) == [0, 3]
    assert lit_lamps(step(effect)) == [0, 2, 3]


def test_room_scatter_never_picks_a_neighbour():
    effect = make_effect(
        pixel_count=8,
        pattern="scatter",
        grouping="room",
        layout="Ring",
        envelope="hold",
        backlight_brightness=0,
    )
    previous = lit_lamps(render_at(effect, 0.0))[0]
    for _ in range(40):
        current = lit_lamps(step(effect))[0]
        assert (current - previous) % 8 not in (0, 1, 7)
        previous = current


def test_room_double_scatter_and_sprinkle_spread_their_lamps():
    for pattern in ("double scatter", "sprinkle"):
        effect = make_effect(
            pixel_count=8,
            pattern=pattern,
            stages=2,
            grouping="room",
            layout="Ring",
            envelope="hold",
            backlight_brightness=0,
        )
        for k in range(30):
            pixels = step(effect)
            lamps = lit_lamps(pixels)
            if len(lamps) != 2:
                import timeit as _t

                info = {
                    "k": k,
                    "pattern": pattern,
                    "now": effect.now,
                    "lit_time": [
                        round(x - effect.now, 6) for x in effect._lit_time.tolist()
                    ],
                    "dur": effect._lit_duration.tolist(),
                    "lit_now": effect._lit_now.tolist(),
                    "step_interval": effect._stepper.step_interval,
                    "last": effect._stepper.last_step_time - effect.now,
                    "timer": _t.default_timer,
                    "rng": np.random.default_rng,
                    "levels": [round(x, 3) for x in pixels.max(axis=1).tolist()],
                    "envelope": effect.envelope,
                    "trail": effect.trail,
                    "rhythm": effect.rhythm,
                    "pending": effect._stepper.pending,
                    "lead": effect._stepper.lead,
                }
                raise AssertionError(f"DEBUGINFO {info}")
            assert (lamps[1] - lamps[0]) % 8 not in (1, 7)


def test_room_wave_follows_the_angle_order():
    room = make_room_effect(
        SCRAMBLED,
        pattern="wave",
        stages=1,
        envelope="hold",
        backlight_brightness=0,
    )
    assert int(np.argmax(bright(render_at(room, 0.25)))) == 0
    order = make_room_effect(
        SCRAMBLED,
        grouping="order",
        pattern="wave",
        stages=1,
        envelope="hold",
        backlight_brightness=0,
    )
    assert int(np.argmax(bright(render_at(order, 0.25)))) == 1


def test_room_per_lamp_colours_follow_the_walk():
    effect = make_room_effect(
        SCRAMBLED,
        pattern="all",
        envelope="hold",
        color_mode="per lamp",
        gradient=RED_BLUE,
        backlight_brightness=0,
    )
    pixels = render_at(effect, 0.0)
    for lamp in SCRAMBLED_WALK[:2]:
        assert np.array_equal(pixels[lamp], [255, 0, 0])
    for lamp in SCRAMBLED_WALK[2:]:
        assert np.array_equal(pixels[lamp], [0, 0, 255])


def test_room_grouping_falls_back_to_a_ring_without_positions():
    effect = make_effect(pixel_count=6, grouping="room", pattern="cycle")
    assert effect._position_source == "ring"
    assert effect._walk.tolist() == list(range(6))
    assert render_at(effect, 0.0).shape == (6, 3)


def test_line_layout_orders_the_lamps_left_to_right():
    effect = make_effect(pixel_count=5, grouping="room", layout="Line", pattern="cycle")
    assert effect._position_source == "line"
    assert effect._walk.tolist() == [0, 1, 2, 3, 4]
    assert effect._opposite.tolist() == [4, 3, 1, 1, 0]


def test_layout_and_grouping_changes_re_resolve_the_positions():
    effect = make_room_effect(SCRAMBLED, pattern="cycle")
    assert effect._position_source == "device"
    effect.update_config({"layout": "Line"})
    assert effect._position_source == "line"
    assert effect._walk.tolist() == [0, 1, 2, 3]
    effect.update_config({"grouping": "order"})
    assert effect._position_source == "order"
    effect.update_config({"grouping": "room", "layout": "Auto"})
    assert effect._walk.tolist() == SCRAMBLED_WALK


def test_zones_share_the_positions_of_their_pixels():
    # Two pixels per lamp: the lamp positions are the pixel means
    positions = [p for corner in CORNERS for p in (corner, corner)]
    effect = make_room_effect(
        positions,
        zones=4,
        pattern="split",
        envelope="hold",
        backlight_brightness=0,
    )
    assert effect._zone_count == 4
    lit = lit_lamps(render_at(effect, 0.0))
    assert lit in ([0, 1, 6, 7], [2, 3, 4, 5])


# ------------------------------------------------------------ settings


def test_auto_sets_and_rhythms_are_consistent():
    for pattern in (
        LightShowEffect.AUTO_LOUD_PATTERNS + LightShowEffect.AUTO_QUIET_PATTERNS
    ):
        assert pattern in LightShowEffect.PATTERNS
    for envelope in (
        LightShowEffect.AUTO_LOUD_ENVELOPES + LightShowEffect.AUTO_QUIET_ENVELOPES
    ):
        assert envelope in LightShowEffect.ENVELOPES
    for mode in LightShowEffect.AUTO_COLOR_MODES:
        assert mode in LightShowEffect.COLOR_MODES
    for rhythm in LightShowEffect.RHYTHMS.values():
        assert set(rhythm) <= {"x", ".", "o"}
        assert rhythm[0] == "x"


def test_sixteen_stages_give_one_lamp_per_stage():
    effect = make_effect(
        pixel_count=16,
        pattern="stage",
        stages=16,
        envelope="hold",
        backlight_brightness=0,
    )
    seen = [lit_lamps(render_at(effect, 0.0))]
    seen += [lit_lamps(step(effect)) for _ in range(15)]
    assert all(len(lamps) == 1 for lamps in seen)
    assert sorted(lamp for frame in seen for lamp in frame) == list(range(16))


def test_pattern_change_starts_the_new_pattern_fresh():
    effect = make_effect(
        pixel_count=4, pattern="fill", envelope="hold", backlight_brightness=0
    )
    step(effect)
    assert len(lit_lamps(render_at(effect, 0.0))) == 2
    effect.update_config({"pattern": "cycle"})
    assert len(lit_lamps(step(effect))) == 1
