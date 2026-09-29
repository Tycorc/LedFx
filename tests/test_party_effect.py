"""Unit tests for the Party effect families."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ledfx.effects import Effect
from ledfx.effects.party import SHAPES, PartyEffect, ahdsr, curve, hash01

FREQS = np.geomspace(20, 15000, 64)
WHITE = "linear-gradient(90deg, #ffffff 0%, #ffffff 100%)"
RED_BLUE = (
    "linear-gradient(90deg, #ff0000 0%, #ff0000 50%, "
    "#0000ff 50%, #0000ff 100%)"
)


def make_effect(pixel_count=4, **config):
    """An activated Party effect on a 60 BPM timer, so one beat is 1 s."""
    config.setdefault("trigger", "Timer")
    config.setdefault("timer_bpm", 60)
    config.setdefault("gradient", WHITE)
    config.setdefault("flash_limit", False)
    effect = PartyEffect(ledfx=MagicMock(), config=config)
    virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    Effect.activate(effect, virtual)
    # Rebase the clocks: the first event started at t=0
    effect._stepper.reset(0.0)
    effect._events = [(0.0, 0)]
    effect._event_index = 0
    effect._last_burst = 0.0
    effect._last_level_time = 0.0
    effect._lamp_last_rise[:] = -np.inf
    effect.now = 0.0
    return effect


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
        for a, b in zip(starts, starts[1:])
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
    assert (
        np.allclose(early, 0.5)
        and np.allclose(peak, 1.0)
        and np.allclose(late, 0.5)
    )


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
    effect = make_effect(
        pixel_count=1, family="adsr", shape="Frost", curve="ease out"
    )
    early = render_at(effect, 0.03)[0]
    late = render_at(effect, 0.25)[0]
    # Frost starts near white and ends on blue
    assert early.min() > 150
    assert late[2] > late[0] and late[2] > late[1]


@pytest.mark.parametrize("family", PartyEffect.FAMILIES)
@pytest.mark.parametrize("pixel_count", [1, 8])
def test_every_family_renders(family, pixel_count):
    effect = make_effect(
        pixel_count=pixel_count, family=family, gradient=RED_BLUE
    )
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
