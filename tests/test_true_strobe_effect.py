"""Unit tests for the True Strobe effect."""

import itertools
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest
import voluptuous as vol

from ledfx.effects import Effect
from ledfx.effects.true_strobe import TrueStrobeEffect

FREQS = np.geomspace(20, 15000, 64)
RED_BLUE = "linear-gradient(90deg, #ff0000 0%, #ff0000 50%, #0000ff 50%, #0000ff 100%)"
RED = np.array([255.0, 0.0, 0.0])
BLUE = np.array([0.0, 0.0, 255.0])
WHITE = np.array([255.0, 255.0, 255.0])

# Four lamps in the corners of a room, clockwise from the front left
CORNERS = np.array(
    [
        [-1.0, 1.0, 0.0],
        [1.0, 1.0, 0.0],
        [1.0, -1.0, 0.0],
        [-1.0, -1.0, 0.0],
    ]
)
# Six lamps on three rings around the centre, innermost first
RINGS = np.array(
    [
        [0.1, 0.0, 0.0],
        [-0.1, 0.0, 0.0],
        [0.5, 0.0, 0.0],
        [-0.5, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [-1.0, 0.0, 0.0],
    ]
)


def make_effect(pixel_count=4, positions=None, seed=None, **config):
    """
    An activated True Strobe on a 60 BPM timer, so one step is 1 s.

    With positions, the virtual gets a fake device that knows where its
    pixels stand. The clocks are rebased so that the run starts at t=0.
    """
    config.setdefault("trigger", "Timer")
    config.setdefault("timer_bpm", 60)
    ledfx = MagicMock()
    if positions is not None:
        ledfx.devices.get.return_value = SimpleNamespace(
            pixel_positions=positions, pixel_count=len(positions)
        )
        virtual = SimpleNamespace(
            effective_pixel_count=pixel_count,
            id="test",
            _segments=[("lamps", 0, pixel_count - 1, False)],
            _config={"mapping": "span"},
            group_size=1,
            rows=1,
        )
    else:
        virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    effect = TrueStrobeEffect(ledfx=ledfx, config=config)
    Effect.activate(effect, virtual)
    if seed is not None:
        effect._rng = np.random.default_rng(seed)
    effect._stepper.reset(0.0)
    effect._level._last_time = 0.0
    effect._start_run(0.0)
    effect.now = 0.0
    return effect


def render_at(effect, t):
    effect.now = t
    effect.render()
    return np.copy(effect.pixels)


def lit_lamps(pixels):
    return [int(i) for i in np.flatnonzero(pixels.max(axis=1) > 0)]


def level(pixels):
    return float(pixels.max()) / 255.0


def flash_starts(effect, times):
    """Times at which the output went from dark to lit."""
    starts = []
    was_lit = False
    for t in times:
        now_lit = render_at(effect, t).max() > 0
        if now_lit and not was_lit:
            starts.append(t)
        was_lit = now_lit
    return starts


def melbank(bass=0.0, mids=0.0, high=0.0):
    frame = np.zeros(len(FREQS))
    frame[(FREQS >= 20) & (FREQS < 250)] = bass
    frame[(FREQS >= 250) & (FREQS < 3000)] = mids
    frame[(FREQS >= 3000) & (FREQS <= 9000)] = high
    return frame


# -------------------------------------------------------------- timing


def test_defaults_are_a_white_eight_hertz_strobe_of_all_lamps():
    effect = make_effect()
    assert effect.rate == 8.0
    assert effect.on_time == 0.05
    assert effect.spread == "all"
    assert effect.color_mode == "strobe color"
    assert effect.gate == "always"
    assert np.array_equal(effect.strobe_color, WHITE)


def test_flashes_follow_the_rate_on_the_render_clock():
    effect = make_effect(rate=4, on_time=0.05)
    # Period 0.25 s, lit for the first 0.05 s of every period
    assert level(render_at(effect, 0.0)) == 1.0
    assert level(render_at(effect, 0.04)) == 1.0
    assert level(render_at(effect, 0.06)) == 0.0
    assert level(render_at(effect, 0.2)) == 0.0
    assert level(render_at(effect, 0.25)) == 1.0
    assert level(render_at(effect, 0.29)) == 1.0
    assert level(render_at(effect, 0.31)) == 0.0
    assert level(render_at(effect, 0.5)) == 1.0


def test_flash_count_matches_the_rate():
    effect = make_effect(rate=5)
    times = [i / 100 for i in range(200)]
    assert len(flash_starts(effect, times)) == 10


def test_on_time_is_clamped_to_half_the_period():
    effect = make_effect(rate=12, on_time=0.3)
    assert effect._on_seconds() == pytest.approx(0.5 / 12)
    assert level(render_at(effect, 0.03)) == 1.0
    assert level(render_at(effect, 0.05)) == 0.0
    slow = make_effect(rate=2, on_time=0.2)
    assert slow._on_seconds() == pytest.approx(0.2)


def test_a_flash_shorter_than_a_frame_still_shows_once():
    effect = make_effect(rate=10, on_time=0.03)
    assert level(render_at(effect, 0.0)) == 1.0
    # The second flash was due at 0.1 and its 30 ms are already over
    # when the next frame comes, but it must still be shown once
    assert level(render_at(effect, 0.14)) == 1.0
    assert level(render_at(effect, 0.16)) == 0.0
    assert level(render_at(effect, 0.2)) == 1.0


def test_thirty_fps_keeps_every_flash_apart_at_the_fastest_rate():
    effect = make_effect(rate=12, on_time=0.3)
    # 30 frames per second at 12 Hz: a flash may span two frames, but
    # two different flashes never touch, every one gets its dark gap
    times = [i / 30 for i in range(60)]
    assert len(flash_starts(effect, times)) == 24
    runs = []
    for t in times:
        if render_at(effect, t).max() > 0:
            runs.append(effect._flash_index)
        else:
            runs.append(None)
    for a, b in itertools.pairwise(runs):
        assert a is None or b is None or a == b


def test_rate_is_capped_at_twelve():
    with pytest.raises(vol.Invalid):
        TrueStrobeEffect.schema()({"rate": 20})
    effect = make_effect(rate=12)
    effect.rate = 30.0
    assert effect._period() == pytest.approx(1.0 / 12)


def test_rate_change_restarts_the_run_on_the_render_clock():
    effect = make_effect(rate=2)
    render_at(effect, 0.0)
    assert level(render_at(effect, 0.3)) == 0.0
    effect.now = 0.3
    effect.update_config({"rate": 10})
    assert effect._origin == 0.3
    assert level(render_at(effect, 0.3)) == 1.0
    assert level(render_at(effect, 0.36)) == 0.0
    assert level(render_at(effect, 0.4)) == 1.0


# ------------------------------------------------------------- spreads


def test_all_lamps_switch_together_in_the_same_frame():
    effect = make_effect(pixel_count=6, spread="all", rate=4)
    on = render_at(effect, 0.0)
    assert np.all(on == WHITE)
    off = render_at(effect, 0.1)
    assert not off.any()


def test_alternate_groups_are_disjoint_and_take_turns():
    effect = make_effect(pixel_count=8, spread="alternate", rate=4)
    first = set(lit_lamps(render_at(effect, 0.0)))
    second = set(lit_lamps(render_at(effect, 0.25)))
    assert len(first) == 4 and len(second) == 4
    assert not first & second
    assert first | second == set(range(8))
    # Interleaved by angle around the ring
    assert first == {0, 2, 4, 6}
    assert set(lit_lamps(render_at(effect, 0.5))) == first


def test_halves_turn_front_back_then_right_left():
    effect = make_effect(positions=CORNERS, spread="halves", rate=4)
    assert effect._position_source == "device"
    halves = [lit_lamps(render_at(effect, k * 0.25)) for k in range(6)]
    front, back, right, left = [0, 1], [2, 3], [1, 2], [0, 3]
    assert halves == [front, back, right, left, front, back]


def test_corners_step_through_balanced_channels():
    effect = make_effect(pixel_count=8, spread="corners", sectors=4, rate=4, seed=1)
    flashes = [lit_lamps(render_at(effect, k * 0.25)) for k in range(5)]
    assert all(len(lamps) == 2 for lamps in flashes)
    assert len({tuple(lamps) for lamps in flashes[:4]}) == 4
    assert sorted(lamp for flash in flashes[:4] for lamp in flash) == list(range(8))
    assert flashes[4] == flashes[0]


def test_corners_never_flash_an_empty_channel():
    effect = make_effect(pixel_count=2, spread="corners", sectors=8, rate=4)
    assert effect._groups == 2
    for k in range(4):
        assert len(lit_lamps(render_at(effect, k * 0.25))) == 1


def test_sweep_goes_round_the_room():
    effect = make_effect(pixel_count=8, spread="sweep", sectors=4, rate=4)
    flashes = [lit_lamps(render_at(effect, k * 0.25)) for k in range(5)]
    assert flashes == [[0, 1], [2, 3], [4, 5], [6, 7], [0, 1]]


def test_ripple_runs_from_the_centre_outwards():
    effect = make_effect(
        pixel_count=6, positions=RINGS, spread="ripple", sectors=3, rate=4
    )
    flashes = [lit_lamps(render_at(effect, k * 0.25)) for k in range(4)]
    assert flashes == [[0, 1], [2, 3], [4, 5], [0, 1]]


def test_scatter_lights_the_density_fraction_and_changes_every_flash():
    effect = make_effect(pixel_count=16, spread="scatter", density=0.5, rate=4, seed=3)
    sets = [set(lit_lamps(render_at(effect, k * 0.25))) for k in range(12)]
    assert all(len(lamps) == 8 for lamps in sets)
    assert len({frozenset(lamps) for lamps in sets}) > 1
    assert set.union(*sets) == set(range(16))
    # Every lamp of a flash switches off in the same frame too
    assert not render_at(effect, 11 * 0.25 + 0.1).any()


def test_scatter_density_one_is_every_lamp():
    effect = make_effect(pixel_count=5, spread="scatter", density=1.0)
    assert lit_lamps(render_at(effect, 0.0)) == [0, 1, 2, 3, 4]


def test_random_lights_one_lamp_and_never_the_same_twice_running():
    effect = make_effect(pixel_count=6, spread="random", rate=4, seed=5)
    lamps = [lit_lamps(render_at(effect, k * 0.25)) for k in range(20)]
    assert all(len(lit) == 1 for lit in lamps)
    assert all(a != b for a, b in itertools.pairwise(lamps))


@pytest.mark.parametrize("spread", TrueStrobeEffect.SPREADS)
@pytest.mark.parametrize("pixel_count", [1, 3, 16])
def test_every_spread_renders_and_flashes(spread, pixel_count):
    effect = make_effect(pixel_count=pixel_count, spread=spread, rate=4)
    lit_any = False
    for k in range(8):
        pixels = render_at(effect, k * 0.25)
        assert pixels.shape == (pixel_count, 3)
        assert pixels.min() >= 0 and pixels.max() <= 255
        lit_any |= pixels.max() > 0
        assert not render_at(effect, k * 0.25 + 0.1).any()
    assert lit_any


# ------------------------------------------------------------- colours


def test_strobe_color_mode_flashes_the_chosen_colour():
    effect = make_effect(pixel_count=3, strobe_color="#00ff00")
    assert np.all(render_at(effect, 0.0) == [0, 255, 0])


def test_palette_cycle_steps_along_the_palette_per_flash():
    effect = make_effect(
        pixel_count=2,
        color_mode="palette cycle",
        color_step=0.6,
        gradient=RED_BLUE,
        rate=4,
    )
    assert np.all(render_at(effect, 0.0) == RED)
    assert np.all(render_at(effect, 0.25) == BLUE)
    assert np.all(render_at(effect, 0.5) == RED)


def test_palette_by_position_colours_every_lamp_by_its_angle():
    effect = make_effect(
        positions=CORNERS,
        color_mode="palette by position",
        gradient=RED_BLUE,
        rate=4,
    )
    pixels = render_at(effect, 0.0)
    # The right hand side of the room is the first half of the palette
    assert np.all(pixels[1] == RED) and np.all(pixels[2] == RED)
    assert np.all(pixels[0] == BLUE) and np.all(pixels[3] == BLUE)
    assert np.array_equal(render_at(effect, 0.25), pixels)


def test_palette_random_picks_a_palette_colour_per_lamp_per_flash():
    effect = make_effect(
        pixel_count=16,
        color_mode="palette random",
        gradient=RED_BLUE,
        rate=4,
        seed=7,
    )
    first = render_at(effect, 0.0)
    assert all(
        np.array_equal(pixel, RED) or np.array_equal(pixel, BLUE) for pixel in first
    )
    assert any(np.array_equal(pixel, RED) for pixel in first)
    assert any(np.array_equal(pixel, BLUE) for pixel in first)
    assert not np.array_equal(render_at(effect, 0.25), first)


# --------------------------------------------------------------- gates


def test_beat_bursts_flash_after_a_step_then_stay_dark():
    effect = make_effect(gate="beat bursts", burst_flashes=4, rate=8)
    times = [i / 100 for i in range(100)]
    starts = flash_starts(effect, times)
    assert starts == pytest.approx([0.0, 0.13, 0.25, 0.38])
    # The next step of the 60 BPM timer starts the next burst
    assert level(render_at(effect, 1.0)) == 1.0


def test_burst_flashes_limits_the_flashes_per_step():
    effect = make_effect(gate="beat bursts", burst_flashes=2, rate=8)
    assert level(render_at(effect, 0.0)) == 1.0
    assert level(render_at(effect, 0.125)) == 1.0
    assert level(render_at(effect, 0.25)) == 0.0
    assert level(render_at(effect, 0.375)) == 0.0
    assert level(render_at(effect, 1.0)) == 1.0


def test_level_gate_only_flashes_while_the_band_is_loud():
    effect = make_effect(gate="level", threshold=0.5, rate=4)
    effect._level.level = 0.2
    assert all(level(render_at(effect, k * 0.25)) == 0.0 for k in range(4))
    effect._level.level = 0.8
    assert level(render_at(effect, 1.0)) == 1.0
    assert level(render_at(effect, 1.25)) == 1.0
    effect._level.level = 0.3
    assert level(render_at(effect, 1.5)) == 0.0


def test_audio_feeds_the_band_level():
    effect = make_effect(gate="level", band="Bass", threshold=0.5)
    melbanks = SimpleNamespace(
        melbanks=[melbank(bass=0.8)],
        melbank_processors=[SimpleNamespace(melbank_frequencies=FREQS)],
    )
    data = SimpleNamespace(melbanks=melbanks)
    for _ in range(40):
        effect.audio_data_updated(data)
    assert effect._level.level > 0.5


def test_reactive_depth_scales_the_flash_with_the_level():
    effect = make_effect(reactive_depth=1.0)
    effect._level.level = 0.5
    assert level(render_at(effect, 0.0)) == pytest.approx(0.5)


# ------------------------------------------------------- tail and background


def test_tail_fades_out_monotonically_over_the_gap():
    effect = make_effect(rate=2, on_time=0.1, tail=1.0)
    assert level(render_at(effect, 0.05)) == 1.0
    fade = [level(render_at(effect, t)) for t in (0.15, 0.25, 0.35, 0.45)]
    assert all(0.0 < value < 1.0 for value in fade)
    assert all(a > b for a, b in itertools.pairwise(fade))
    assert level(render_at(effect, 0.5)) == 1.0


def test_tail_zero_is_a_hard_off():
    effect = make_effect(rate=2, on_time=0.1, tail=0.0)
    assert level(render_at(effect, 0.09)) == 1.0
    assert level(render_at(effect, 0.11)) == 0.0


def test_last_flash_of_a_burst_fades_towards_the_next_step():
    effect = make_effect(gate="beat bursts", burst_flashes=2, rate=8, tail=1.0)
    render_at(effect, 0.0)
    render_at(effect, 0.125)
    fade = [level(render_at(effect, t)) for t in (0.3, 0.5, 0.7, 0.9)]
    assert all(0.0 < value < 1.0 for value in fade)
    assert all(a > b for a, b in itertools.pairwise(fade))


def test_background_keeps_the_lamps_dimly_lit_between_flashes():
    effect = make_effect(pixel_count=3, rate=4, background=0.3)
    assert np.all(render_at(effect, 0.0) == WHITE)
    between = render_at(effect, 0.1)
    assert np.allclose(between, WHITE * 0.3)


def test_background_shows_each_lamps_own_palette_colour():
    effect = make_effect(
        positions=CORNERS,
        color_mode="palette by position",
        gradient=RED_BLUE,
        rate=4,
        background=0.5,
    )
    render_at(effect, 0.0)
    between = render_at(effect, 0.1)
    assert np.allclose(between[1], RED * 0.5)
    assert np.allclose(between[0], BLUE * 0.5)


# ------------------------------------------------------------ layouts


def test_positions_come_from_the_virtual_devices():
    effect = make_effect(positions=CORNERS)
    assert effect._position_source == "device"
    assert np.allclose(effect._positions, CORNERS)


def test_ring_fallback_without_device_positions():
    effect = make_effect(pixel_count=4)
    assert effect._position_source == "ring"
    assert effect._angles == pytest.approx([0.0, 0.25, 0.5, 0.75])


def test_line_layout_can_be_forced():
    effect = make_effect(pixel_count=3, layout="Line")
    assert effect._position_source == "line"
    assert effect._positions[:, 0].tolist() == [-1.0, 0.0, 1.0]


def test_zones_group_a_strip_into_lamps():
    effect = make_effect(
        pixel_count=120, zones=4, layout="Ring", spread="sweep", sectors=4
    )
    assert effect._zone_count == 4
    for k in range(4):
        lamps = lit_lamps(render_at(effect, k * 0.125))
        assert lamps == list(range(k * 30, k * 30 + 30))


def test_auto_zones_one_per_pixel_for_bulbs_and_blocks_for_strips():
    assert make_effect(pixel_count=16)._zone_count == 16
    assert make_effect(pixel_count=300)._zone_count == 8
    assert make_effect(pixel_count=3, zones=10)._zone_count == 3


def test_layout_change_rebuilds_the_lamps():
    effect = make_effect(pixel_count=4)
    assert effect._position_source == "ring"
    effect.update_config({"layout": "Line"})
    assert effect._position_source == "line"
