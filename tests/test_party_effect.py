"""Unit tests for the Party effect families."""

import itertools
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ledfx.effects import Effect
from ledfx.effects.party import SHAPES, PartyEffect, ahdsr, curve, hash01

FREQS = np.geomspace(20, 15000, 64)
WHITE = "linear-gradient(90deg, #ffffff 0%, #ffffff 100%)"
RED_BLUE = "linear-gradient(90deg, #ff0000 0%, #ff0000 50%, #0000ff 50%, #0000ff 100%)"
RED = "linear-gradient(90deg, #ff0000 0%, #ff0000 100%)"
THIRDS = (
    "linear-gradient(90deg, #ff0000 0%, #ff0000 33.3%, "
    "#00ff00 33.3%, #00ff00 66.6%, #0000ff 66.6%, #0000ff 100%)"
)
# Four corner lamps: back left, front right, front left, back right
CORNERS = [(-1, -1, 0), (1, 1, 0), (-1, 1, 0), (1, -1, 0)]
# Five lamps in a line from left to right
LINE = [(-1, 0, 0), (-0.5, 0, 0), (0, 0, 0), (0.5, 0, 0), (1, 0, 0)]
# Three lamps in a line, in scrambled pixel order: right, left, middle
SCRAMBLED = [(1, 0, 0), (-1, 0, 0), (0, 0, 0)]


def make_effect(pixel_count=4, ledfx=None, virtual=None, seed=None, **config):
    """An activated Party effect on a 60 BPM timer, so one beat is 1 s."""
    config.setdefault("trigger", "Timer")
    config.setdefault("timer_bpm", 60)
    config.setdefault("gradient", WHITE)
    config.setdefault("flash_limit", False)
    effect = PartyEffect(ledfx=ledfx or MagicMock(), config=config)
    if virtual is None:
        virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    Effect.activate(effect, virtual)
    if seed is not None:
        # A fixed seed makes the hashed choices of a test reproducible
        effect._seed = seed
        effect._order_lamps()
    # Rebase the clocks: the first event started at t=0
    effect._stepper.reset(0.0)
    effect._events = [(0.0, 0)]
    effect._event_index = 0
    effect._fire_origins = {}
    effect._last_burst = 0.0
    effect._last_level_time = 0.0
    effect._limiter.reset(effect._zone_count)
    effect.now = 0.0
    return effect


def make_spatial(positions, **config):
    """A Party effect on a fake device that knows where its lamps are."""
    positions = np.asarray(positions, dtype=float)
    count = len(positions)
    ledfx = MagicMock()
    ledfx.devices.get.return_value = SimpleNamespace(
        pixel_positions=positions, pixel_count=count
    )
    virtual = SimpleNamespace(
        effective_pixel_count=count,
        id="test",
        _segments=[("hue", 0, count - 1, False)],
        _config={"mapping": "span"},
        group_size=1,
        rows=1,
    )
    return make_effect(pixel_count=count, ledfx=ledfx, virtual=virtual, **config)


def render_at(effect, t):
    effect.now = t
    effect.render()
    return np.copy(effect.pixels)


def levels(pixels):
    return pixels.max(axis=1) / 255.0


def melbank(bass=0.0, mids=0.0, high=0.0):
    frame = np.zeros(len(FREQS))
    frame[(FREQS >= 20) & (FREQS < 250)] = bass
    frame[(FREQS >= 250) & (FREQS < 3000)] = mids
    frame[(FREQS >= 3000) & (FREQS <= 9000)] = high
    return frame


# ------------------------------------------------------------ helpers


def test_curves_run_from_zero_to_one():
    for kind in PartyEffect.CURVES:
        assert curve(0.0, kind) == 0.0 or kind == "cut"
        assert curve(1.0, kind) == pytest.approx(1.0)
    assert curve(0.5, "ease in") < 0.5 < curve(0.5, "ease out")
    assert curve(0.25, "cut") == 1.0


def test_ahdsr_walks_through_its_phases():
    envelope = (0.1, 0.1, 0.2, 0.5, 0.2, 1.0)
    assert ahdsr(envelope, 0.0, "linear") == 0.0
    assert ahdsr(envelope, 0.05, "linear") == pytest.approx(0.5)
    assert ahdsr(envelope, 0.15, "linear") == 1.0
    assert ahdsr(envelope, 0.3, "linear") == pytest.approx(0.75)
    assert ahdsr(envelope, 0.6, "linear") == 0.5
    assert ahdsr(envelope, 0.9, "linear") == pytest.approx(0.25)
    assert ahdsr(envelope, 1.0, "linear") == 0.0


def test_ahdsr_normalises_overlong_phases():
    envelope = (1.0, 1.0, 1.0, 0.0, 1.0, 1.0)
    assert ahdsr(envelope, 0.125, "linear") == pytest.approx(0.5)


def test_hash_is_deterministic_and_spread():
    a = hash01(7, [1, 2, 3], 4)
    b = hash01(7, [1, 2, 3], 4)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, hash01(7, [1, 2, 3], 5))
    assert np.all((a >= 0) & (a < 1))
    spread = hash01(1, np.arange(1000), 0)
    assert 0.4 < spread.mean() < 0.6


# ------------------------------------------------------------- events


def test_timer_steps_start_new_events():
    effect = make_effect(family="breathe", attack=0.2, hold=0.2, release=0.2)
    render_at(effect, 0.5)
    assert [index for _, index in effect._events] == [0]
    render_at(effect, 1.0)
    assert [index for _, index in effect._events][-1] == 1


def test_old_events_are_pruned():
    effect = make_effect(family="breathe", attack=0.1, hold=0.1, release=0.1)
    render_at(effect, 0.9)
    assert effect._events == []


def test_burst_events_keep_their_distance():
    effect = make_effect(family="burst", steps_per_beat="4")
    # Steps every 0.25 s, bursts at most every 0.4 s
    for t in (0.25, 0.5, 0.75, 1.0):
        render_at(effect, t)
    starts = [start for start, _ in effect._events]
    assert all(
        b - a >= PartyEffect.BURST_INTERVAL - 1e-9
        for a, b in itertools.pairwise(starts)
    )


# ------------------------------------------------------------ families


def test_chase_runs_along_the_lamps():
    effect = make_effect(
        pixel_count=4,
        family="chase",
        stagger=0.25,
        attack=0.05,
        hold=0.2,
        release=0.05,
        curve="linear",
    )
    first = levels(render_at(effect, 0.1))
    assert first[0] == pytest.approx(1.0)
    assert first[1:].max() == 0.0
    second = levels(render_at(effect, 0.35))
    assert second[1] == pytest.approx(1.0)
    assert second[0] == 0.0
    assert second[2:].max() == 0.0


def test_reverse_direction_starts_at_the_last_lamp():
    effect = make_effect(
        pixel_count=4,
        family="chase",
        direction="reverse",
        stagger=0.25,
        attack=0.05,
        hold=0.2,
        release=0.05,
    )
    first = levels(render_at(effect, 0.1))
    assert first[3] == pytest.approx(1.0)
    assert first[:3].max() == 0.0


def test_alternate_direction_flips_every_event():
    effect = make_effect(family="chase", direction="alternate")
    assert not effect._reversed(0)
    assert effect._reversed(1)
    assert not effect._reversed(2)


def test_radial_spreads_from_the_origin():
    effect = make_effect(
        pixel_count=5,
        family="radial",
        origin=0.5,
        attack=0.0,
        hold=1.0,
        release=0.0,
        curve="linear",
    )
    start = levels(render_at(effect, 0.01))
    assert start[2] == start.max()
    assert start[0] < start[2]
    late = levels(render_at(effect, 0.95))
    assert late[0] > late[2]
    assert late[4] > late[2]


def test_scan_moves_a_line_back_and_forth():
    effect = make_effect(
        pixel_count=5,
        family="scan",
        attack=0.0,
        hold=1.0,
        release=0.0,
        trail=0.1,
    )
    assert np.argmax(levels(render_at(effect, 0.02))) == 0
    assert np.argmax(levels(render_at(effect, 0.5))) == 4
    assert np.argmax(levels(render_at(effect, 0.98))) == 0


def test_streak_trails_behind_its_head():
    effect = make_effect(
        pixel_count=5,
        family="streak",
        probability=1.0,
        attack=0.0,
        hold=1.0,
        release=0.0,
        trail=0.3,
    )
    mid = levels(render_at(effect, 0.5))
    assert mid[2] > mid[1] > mid[0]
    assert mid[3] == 0.0 and mid[4] == 0.0


def test_streak_probability_skips_events():
    effect = make_effect(
        pixel_count=5,
        family="streak",
        probability=0.0,
        attack=0.0,
        hold=1.0,
        release=0.0,
    )
    assert render_at(effect, 0.5).max() == 0.0


def test_twinkle_lights_a_random_subset_that_changes_per_event():
    effect = make_effect(
        pixel_count=16,
        family="twinkle",
        probability=0.5,
        attack=0.0,
        hold=0.5,
        release=0.0,
    )
    first = levels(render_at(effect, 0.1)) > 0
    assert 0 < first.sum() < 16
    # The same event keeps the same lamps, the next event picks new ones
    assert np.array_equal(first, levels(render_at(effect, 0.3)) > 0)
    second = levels(render_at(effect, 1.1)) > 0
    assert not np.array_equal(first, second)


def test_breathe_rises_and_falls_together():
    effect = make_effect(
        pixel_count=3,
        family="breathe",
        attack=0.4,
        hold=0.2,
        release=0.4,
        curve="linear",
    )
    early = levels(render_at(effect, 0.2))
    peak = levels(render_at(effect, 0.5))
    late = levels(render_at(effect, 0.8))
    assert np.allclose(early, 0.5) and np.allclose(peak, 1.0) and np.allclose(late, 0.5)


def test_wash_keeps_every_lamp_lit():
    effect = make_effect(
        pixel_count=5, family="wash", attack=0.0, hold=1.0, release=0.0
    )
    lit = levels(render_at(effect, 0.5))
    assert lit.min() >= 0.55 - 1e-6
    assert lit.max() <= 1.0


def test_gate_opens_with_the_level():
    effect = make_effect(
        pixel_count=3,
        family="gate",
        threshold=0.2,
        attack=0.0,
        hold=1.0,
        release=0.0,
    )
    closed = levels(render_at(effect, 0.5))
    effect._levels[:] = 1.0
    open_ = levels(render_at(effect, 0.5))
    assert np.allclose(open_ / closed, 5.0)


def test_reactive_depth_scales_with_the_band_level():
    effect = make_effect(
        pixel_count=2,
        family="breathe",
        band="Bass",
        reactive_depth=0.5,
        attack=0.0,
        hold=1.0,
        release=0.0,
    )
    effect._levels[1] = 0.0
    quiet = levels(render_at(effect, 0.5))
    effect._levels[1] = 1.0
    loud = levels(render_at(effect, 0.5))
    assert np.allclose(quiet, 0.5) and np.allclose(loud, 1.0)


def test_adsr_single_colour_plays_the_brightness_envelope():
    effect = make_effect(
        pixel_count=2,
        family="adsr",
        shape="Single colour",
        color="#00ff00",
        curve="linear",
    )
    assert render_at(effect, 0.0).max() == 0.0
    peak = render_at(effect, 0.04)
    assert np.allclose(peak, [0, 255, 0], atol=1)
    assert render_at(effect, 0.99).max() < 5


def test_adsr_colour_shapes_change_colour_over_the_event():
    effect = make_effect(pixel_count=1, family="adsr", shape="Frost", curve="ease out")
    early = render_at(effect, 0.03)[0]
    late = render_at(effect, 0.25)[0]
    # Frost starts near white and ends on blue
    assert early.min() > 150
    assert late[2] > late[0] and late[2] > late[1]


@pytest.mark.parametrize("family", PartyEffect.FAMILIES)
@pytest.mark.parametrize("pixel_count", [1, 8])
def test_every_family_renders(family, pixel_count):
    effect = make_effect(pixel_count=pixel_count, family=family, gradient=RED_BLUE)
    for t in (0.1, 0.6, 1.2, 2.5):
        pixels = render_at(effect, t)
        assert pixels.shape == (pixel_count, 3)
        assert pixels.min() >= 0 and pixels.max() <= 255


@pytest.mark.parametrize("shape", list(SHAPES.keys()))
def test_every_shape_renders(shape):
    effect = make_effect(pixel_count=2, family="adsr", shape=shape)
    for t in (0.02, 0.3, 0.7):
        pixels = render_at(effect, t)
        assert pixels.min() >= 0 and pixels.max() <= 255


# ---------------------------------------------------------------- audio


def test_measure_follows_attack_and_release():
    effect = make_effect(smoothing=0.0)
    for i in range(30):
        effect.measure(melbank(0.5, 0.5, 0.5), FREQS, 0.01 * i)
    loud = effect._levels.copy()
    assert loud[0] > 0.5
    for i in range(30):
        effect.measure(melbank(), FREQS, 0.3 + 0.01 * i)
    quieter = effect._levels
    assert np.all(quieter < loud)
    assert quieter[0] > 0.0  # release is slower than attack


def test_measure_splits_the_bands():
    effect = make_effect(smoothing=0.0)
    for i in range(50):
        effect.measure(melbank(bass=0.8), FREQS, 0.01 * i)
    assert effect._levels[1] > effect._levels[2]
    assert effect._levels[3] == pytest.approx(0.0, abs=1e-6)


def test_flash_limiter_suppresses_quick_second_rises():
    effect = make_effect(
        pixel_count=1,
        family="breathe",
        flash_limit=True,
        attack=0.0,
        hold=0.1,
        release=0.0,
        steps_per_beat="4",
    )
    # Events every 0.25 s, each rising straight to full for 0.1 s
    assert levels(render_at(effect, 0.05))[0] == 1.0
    assert levels(render_at(effect, 0.15))[0] == 0.0
    # The second rise comes 0.25 s after the first, too soon
    assert levels(render_at(effect, 0.3))[0] == 0.0
    assert levels(render_at(effect, 0.34))[0] == 0.0
    # The third is half a second after the first and gets through
    assert levels(render_at(effect, 0.55))[0] == 1.0


def test_random_order_still_uses_every_lamp():
    effect = make_effect(pixel_count=6, family="chase", order="Random")
    assert sorted(effect._rank.tolist()) == list(range(6))


# ------------------------------------------------------------- layout


def longest_run(lit):
    """Longest run of adjacent lit lamps around a ring."""
    n = len(lit)
    best = current = 0
    for i in range(2 * n):
        current = current + 1 if lit[i % n] else 0
        best = max(best, current)
    return min(best, n)


def test_auto_layout_without_positions_runs_along_the_lamps():
    effect = make_effect()
    assert effect._layout_source == "ring"
    assert not effect._spatial


def test_explicit_layout_makes_the_effect_spatial():
    effect = make_effect(pixel_count=4, layout="Line")
    assert effect._layout_source == "line"
    assert effect._spatial
    assert np.all(np.diff(effect._positions[:, 0]) > 0)


def test_device_positions_are_used_as_placed():
    effect = make_spatial(CORNERS)
    assert effect._layout_source == "device"
    assert effect._spatial
    assert np.allclose(effect._positions, CORNERS)


def test_positions_keep_the_room_centre():
    # Lamps all along the front wall stay there: the room centre is 0, 0
    effect = make_spatial([(-1, 1, 0), (0, 1, 0), (1, 1, 0)])
    assert np.allclose(effect._positions[:, 1], 1.0)


def test_layout_change_recomputes_the_positions():
    effect = make_effect()
    assert not effect._spatial
    effect.update_config({"layout": "Ring"})
    assert effect._layout_source == "ring"
    assert effect._spatial


def test_zones_take_the_positions_of_their_pixels():
    effect = make_effect(pixel_count=64, zones=8, layout="Line")
    assert effect._positions.shape == (8, 3)
    assert np.all(np.diff(effect._positions[:, 0]) > 0)


def test_heading_projection_is_normalised():
    effect = make_spatial(CORNERS, heading=45)
    assert effect._proj.min() == pytest.approx(0.0)
    assert effect._proj.max() == pytest.approx(1.0)


def test_spread_jitter_follows_the_lamp_spacing():
    effect = make_effect(pixel_count=16, layout="Ring")
    spacing = 2 * np.sin(np.pi / 16)
    assert effect._spread_jitter == pytest.approx(PartyEffect.SPREAD_JITTER * spacing)


# -------------------------------------------------------------- orders


def test_room_order_ranks_lamps_clockwise_from_the_front():
    effect = make_spatial(CORNERS, order="Room")
    # front right, back right, back left, front left
    assert effect._rank.tolist() == [2, 0, 3, 1]


def test_room_order_falls_back_to_the_pixel_order_without_positions():
    effect = make_effect(pixel_count=4, order="Room")
    assert effect._rank.tolist() == [0, 1, 2, 3]


def test_heading_order_sorts_lamps_along_the_heading():
    lamps = [(0.5, 0, 0), (-1, 0, 0), (1, 0, 0), (-0.5, 0, 0)]
    effect = make_spatial(lamps, order="Heading", heading=90)
    assert effect._rank.tolist() == [2, 0, 3, 1]


def test_room_chase_turns_the_room():
    effect = make_spatial(
        CORNERS,
        family="chase",
        order="Room",
        stagger=0.25,
        attack=0.05,
        hold=0.2,
        release=0.05,
        curve="linear",
    )
    first = levels(render_at(effect, 0.1))
    assert first[1] == pytest.approx(1.0)  # front right first
    assert first[[0, 2, 3]].max() == 0.0
    second = levels(render_at(effect, 0.35))
    assert second[3] == pytest.approx(1.0)  # then back right
    assert second[1] == 0.0


# ------------------------------------------------------ spatial families


def test_radial_grows_from_the_room_centre():
    lamps = [(0, 0, 0), (0.3, 0, 0), (1, 0, 0), (0, -1, 0)]
    effect = make_spatial(
        lamps,
        family="radial",
        origin=0.5,
        attack=0.0,
        hold=1.0,
        release=0.0,
        curve="linear",
    )
    start = levels(render_at(effect, 0.01))
    assert start[0] == pytest.approx(1.0)
    assert 0.0 < start[1] < start[0]
    assert start[2] == 0.0 and start[3] == 0.0
    late = levels(render_at(effect, 0.95))
    assert late[2] > late[0] and late[3] > late[0]


def test_radial_origin_slides_along_the_heading():
    lamps = [(0, 0, 0), (0.3, 0, 0), (1, 0, 0), (0, -1, 0)]
    effect = make_spatial(
        lamps,
        family="radial",
        origin=0.0,
        heading=0,
        attack=0.0,
        hold=1.0,
        release=0.0,
        curve="linear",
    )
    # Origin 0 with heading 0 is the back end of the room
    start = levels(render_at(effect, 0.01))
    assert start[3] == pytest.approx(1.0)
    assert start[[0, 1, 2]].max() < start[3]


def test_wash_crest_follows_the_heading():
    effect = make_spatial(
        LINE, family="wash", heading=90, attack=0.0, hold=1.0, release=0.0
    )
    quarter = levels(render_at(effect, 0.25))
    assert quarter[1] == pytest.approx(1.0)
    assert quarter[3] < 0.9
    three = levels(render_at(effect, 0.75))
    assert three[3] == pytest.approx(1.0)
    assert three[1] < 0.9


def test_reverse_wash_runs_the_other_way():
    effect = make_spatial(
        LINE,
        family="wash",
        heading=90,
        direction="reverse",
        attack=0.0,
        hold=1.0,
        release=0.0,
    )
    quarter = levels(render_at(effect, 0.25))
    assert quarter[3] == pytest.approx(1.0)
    assert quarter[1] < 0.9


def test_reverse_wash_runs_the_other_way_along_the_lamps_too():
    effect = make_effect(
        pixel_count=5,
        family="wash",
        direction="reverse",
        attack=0.0,
        hold=1.0,
        release=0.0,
    )
    quarter = levels(render_at(effect, 0.25))
    assert quarter[3] == pytest.approx(1.0)
    assert quarter[1] < 0.9


def test_scan_bounces_along_the_heading():
    effect = make_spatial(
        SCRAMBLED,
        family="scan",
        heading=90,
        attack=0.0,
        hold=1.0,
        release=0.0,
        trail=0.1,
    )
    # From the left lamp (pixel 1) to the right lamp (pixel 0) and back
    assert np.argmax(levels(render_at(effect, 0.02))) == 1
    assert np.argmax(levels(render_at(effect, 0.5))) == 0
    assert np.argmax(levels(render_at(effect, 0.98))) == 1


def test_streak_crosses_along_the_heading():
    effect = make_spatial(
        SCRAMBLED,
        family="streak",
        heading=90,
        probability=1.0,
        attack=0.0,
        hold=1.0,
        release=0.0,
        trail=1.0,
    )
    mid = levels(render_at(effect, 0.5))
    assert mid[2] == pytest.approx(1.0)  # the head is in the middle
    assert 0.0 < mid[1] < mid[2]  # the left lamp trails behind
    assert mid[0] == 0.0  # the right lamp is still ahead


def test_twinkle_spreads_over_the_room():
    effect = make_effect(
        pixel_count=16,
        family="twinkle",
        layout="Ring",
        probability=0.5,
        attack=0.0,
        hold=0.5,
        release=0.0,
        seed=3,
    )
    first = levels(render_at(effect, 0.1)) > 0
    assert first.sum() == 8
    assert first[:8].sum() >= 3 and first[8:].sum() >= 3
    assert longest_run(first) <= 3
    second = levels(render_at(effect, 1.1)) > 0
    assert not np.array_equal(first, second)


def test_burst_spreads_over_the_room():
    effect = make_effect(
        pixel_count=16,
        family="burst",
        layout="Ring",
        probability=0.5,
        attack=0.0,
        hold=0.5,
        release=0.0,
        seed=3,
    )
    effect._levels[:] = 1.0
    lit = levels(render_at(effect, 0.1)) > 0
    assert lit.sum() == 8
    assert lit[:8].sum() >= 3 and lit[8:].sum() >= 3
    assert longest_run(lit) <= 3


def test_spread_pick_takes_all_or_none_at_the_extremes():
    effect = make_effect(pixel_count=8, layout="Ring")
    assert effect._spread_pick(1.0, 0).all()
    assert not effect._spread_pick(0.0, 0).any()
    assert effect._spread_pick(0.5, 0).sum() == 4


# ---------------------------------------------------------- lightning


def seed_with_flashes(effect, minimum):
    for seed in range(1, 200):
        effect._seed = seed
        if effect._flash_count(0) >= minimum:
            return seed
    raise AssertionError("no seed with enough flashes")


def test_lightning_strikes_white_then_glows_in_the_palette():
    effect = make_effect(
        pixel_count=4,
        family="lightning",
        probability=1.0,
        attack=0.0,
        hold=0.2,
        release=0.5,
        curve="linear",
        gradient=RED,
    )
    effect._seed = 1
    while effect._flash_count(0) != 1:
        effect._seed += 1
    flash = render_at(effect, 0.02)
    assert np.allclose(flash, 255.0)
    glow = render_at(effect, 0.5)
    assert np.allclose(levels(glow), 0.4)
    assert np.all(glow[:, 0] > glow[:, 2])  # reddening after-glow
    rest = levels(render_at(effect, 0.9))
    assert np.all((rest > 0.1) & (rest < 0.2))
    assert np.all(render_at(effect, 0.9)[:, 1] == 0)  # pure palette red


def test_lightning_flicker_dips_to_the_flicker_level():
    effect = make_effect(
        pixel_count=4,
        family="lightning",
        probability=1.0,
        attack=0.0,
        hold=0.5,
        release=0.5,
    )
    seed_with_flashes(effect, 2)
    on = PartyEffect.FLICKER_ON
    dip = PartyEffect.FLICKER_DIP
    assert np.allclose(levels(render_at(effect, 0.02)), 1.0)
    assert np.allclose(levels(render_at(effect, on + 0.01)), PartyEffect.FLICKER_LEVEL)
    assert np.allclose(levels(render_at(effect, on + dip + 0.02)), 1.0)
    assert np.allclose(levels(render_at(effect, 0.45)), 1.0)


def test_lightning_strike_counts_as_one_flash_for_the_limiter():
    effect = make_effect(
        pixel_count=2,
        family="lightning",
        flash_limit=True,
        probability=1.0,
        attack=0.0,
        hold=0.5,
        release=0.5,
    )
    seed_with_flashes(effect, 2)
    on = PartyEffect.FLICKER_ON
    dip = PartyEffect.FLICKER_DIP
    assert np.allclose(levels(render_at(effect, 0.02)), 1.0)
    assert np.allclose(levels(render_at(effect, on + 0.01)), PartyEffect.FLICKER_LEVEL)
    # The second flash is not a new rise, so it is not suppressed
    assert np.allclose(levels(render_at(effect, on + dip + 0.02)), 1.0)


def test_lightning_probability_picks_random_lamps():
    effect = make_effect(
        pixel_count=16,
        family="lightning",
        probability=0.5,
        attack=0.0,
        hold=0.2,
        release=0.5,
    )
    struck = levels(render_at(effect, 0.02)) > 0.5
    assert 0 < struck.sum() < 16


def test_lightning_keeps_a_dim_wobbling_glow_between_strikes():
    effect = make_effect(
        pixel_count=6, family="lightning", probability=0.0, gradient=RED
    )
    glow = np.array([levels(render_at(effect, t)) for t in (0.3, 0.55, 0.8)])
    assert glow.min() >= PartyEffect.GLOW_BASE - 1e-9
    assert glow.max() <= PartyEffect.GLOW_BASE + PartyEffect.GLOW_WOBBLE + 1e-9
    assert glow.std() > 0.0


# ---------------------------------------------------------- fireworks


def test_fireworks_bursts_from_one_lamp_then_spreads():
    effect = make_effect(
        pixel_count=5,
        family="fireworks",
        stagger=0.5,
        attack=0.0,
        hold=0.2,
        release=1.0,
        probability=1.0,
        curve="linear",
        seed=1,
    )
    origin = effect._fire_origin(0)
    first = levels(render_at(effect, 0.05))
    assert first[origin] == pytest.approx(1.0)
    assert (first > 0).sum() == 1
    later = levels(render_at(effect, 0.3))
    assert later[origin] == pytest.approx(0.9)
    others = np.delete(later, origin)
    assert others.max() > 0.0
    assert others.max() < later[origin]


def test_fireworks_never_bursts_from_the_same_lamp_twice():
    effect = make_effect(pixel_count=5, family="fireworks", probability=1.0)
    for t in range(1, 12):
        render_at(effect, float(t))
    origins = [effect._fire_origins[i] for i in range(12)]
    assert all(a != b for a, b in itertools.pairwise(origins))


def test_fireworks_radius_limits_the_spread():
    effect = make_effect(
        pixel_count=5,
        family="fireworks",
        stagger=0.5,
        attack=0.0,
        hold=0.2,
        release=1.0,
        probability=1.0,
        radius=0.3,
        seed=1,
    )
    distance = effect._lamp_distance[effect._fire_origin(0)]
    # Sample the first event only: the next burst starts at t=1
    peak = np.zeros(5)
    for t in np.arange(0.0, 0.95, 0.05):
        peak = np.maximum(peak, levels(render_at(effect, t)))
    assert np.all(peak[distance > 0.3] == 0.0)
    assert np.all(peak[distance <= 0.3] > 0.0)


def test_fireworks_probability_skips_events():
    effect = make_effect(pixel_count=5, family="fireworks", probability=0.0)
    assert render_at(effect, 0.1).max() == 0.0
    assert render_at(effect, 0.5).max() == 0.0


def test_fireworks_sparkle_dims_the_fading_tail():
    effect = make_effect(
        pixel_count=5,
        family="fireworks",
        stagger=0.0,
        attack=0.0,
        hold=0.2,
        release=1.0,
        probability=1.0,
        curve="linear",
        seed=1,
    )
    origin = effect._fire_origin(0)
    # No sparkle while bright: exactly the envelope
    assert levels(render_at(effect, 0.5))[origin] == pytest.approx(0.7)
    # In the tail the envelope is 0.25 and the sparkle, which grows as
    # the lamp fades below half, takes some of it
    tail = levels(render_at(effect, 0.95))[origin]
    assert 0.25 * (1.0 - PartyEffect.SPARKLE_DEPTH * 0.5) - 1e-9 <= tail
    assert tail <= 0.25


# -------------------------------------------------------------- pulse


def test_pulse_meters_each_band_on_its_own_lamps():
    effect = make_effect(pixel_count=3, family="pulse", threshold=0.0, gradient=THIRDS)
    effect._levels[:] = [0.0, 1.0, 0.5, 0.2]
    pixels = render_at(effect, 0.1)
    floor = PartyEffect.METER_FLOOR
    expected = floor + (1 - floor) * np.array([1.0, 0.5, 0.2])
    assert np.allclose(levels(pixels), expected)
    assert np.argmax(pixels, axis=1).tolist() == [0, 1, 2]  # red green blue


def test_pulse_single_band_drives_every_lamp():
    effect = make_effect(pixel_count=3, family="pulse", band="Bass")
    effect._levels[:] = [0.0, 0.6, 0.1, 0.9]
    lit = levels(render_at(effect, 0.1))
    assert np.allclose(lit, lit[0])
    assert lit[0] > PartyEffect.METER_FLOOR


def test_pulse_threshold_squelches_quiet_bands():
    effect = make_effect(pixel_count=3, family="pulse", band="Bass", threshold=0.3)
    effect._levels[:] = [0.0, 0.2, 0.2, 0.2]
    assert np.allclose(levels(render_at(effect, 0.1)), PartyEffect.METER_FLOOR)
    effect._levels[:] = [0.0, 0.65, 0.2, 0.2]
    floor = PartyEffect.METER_FLOOR
    assert np.allclose(levels(render_at(effect, 0.1)), floor + (1 - floor) * 0.5)


# ------------------------------------------------------ reactive depth


def test_gate_uses_the_configured_reactive_depth():
    effect = make_effect(
        pixel_count=2,
        family="gate",
        reactive_depth=0.5,
        threshold=0.2,
        attack=0.0,
        hold=1.0,
        release=0.0,
    )
    closed = levels(render_at(effect, 0.5))
    effect._levels[:] = 1.0
    open_ = levels(render_at(effect, 0.5))
    assert np.allclose(open_ / closed, 2.0)


def test_burst_uses_its_default_depth_while_unset():
    effect = make_effect(
        pixel_count=2,
        family="burst",
        threshold=0.2,
        attack=0.0,
        hold=1.0,
        release=0.0,
    )
    closed = levels(render_at(effect, 0.5))
    effect._levels[:] = 1.0
    open_ = levels(render_at(effect, 0.5))
    assert np.allclose(open_ / closed, 1.0 / (1.0 - PartyEffect.BURST_DEPTH))
