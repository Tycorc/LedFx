"""Unit tests for the Orbit effect modes."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from ledfx.effects import Effect
from ledfx.effects.orbit import OrbitEffect

FREQS = np.geomspace(20, 15000, 64)
# Four hard colour bands whose edges stay clear of the lamp angles used here
BANDS = (
    "linear-gradient(90deg, #ff0000 0%, #ff0000 20%, #00ff00 20%, "
    "#00ff00 45%, #0000ff 45%, #0000ff 70%, #ffffff 70%, #ffffff 100%)"
)
SMOOTH = "linear-gradient(90deg, #ff0000 0%, #0000ff 100%)"
RED = np.array([255, 0, 0])
GREEN = np.array([0, 255, 0])
BLUE = np.array([0, 0, 255])
WHITE = np.array([255, 255, 255])


def make_effect(pixel_count=8, virtual=None, ledfx=None, **config):
    """An activated Orbit effect on a 60 BPM timer, so one beat is 1 s."""
    config.setdefault("trigger", "Timer")
    config.setdefault("timer_bpm", 60)
    config.setdefault("gradient", BANDS)
    config.setdefault("layout", "Ring")
    config.setdefault("flash_limit", False)
    config.setdefault("reactive_depth", 0.0)
    config.setdefault("background", 0.0)
    config.setdefault("softness", 0.0)
    config.setdefault("beats_per_turn", 4)
    effect = OrbitEffect(ledfx=ledfx or MagicMock(), config=config)
    if virtual is None:
        virtual = SimpleNamespace(effective_pixel_count=pixel_count, id="test")
    Effect.activate(effect, virtual)
    rebase(effect)
    return effect


def rebase(effect, seed=7):
    """Rebase every clock to t=0 and make the run deterministic."""
    effect._rng = np.random.default_rng(seed)
    effect._build_noise(seed)
    effect._stepper.reset(0.0)
    effect._band._last_time = 0.0
    effect._sections.reset(0.0)
    effect._limiter.reset(effect._zone_count)
    effect._last_time = 0.0
    effect._reset_state(0.0)
    effect.now = 0.0


def fake_room(positions):
    """A virtual over one device that knows where its lamps are."""
    positions = np.asarray(positions, dtype=float)
    n = len(positions)
    virtual = SimpleNamespace(
        effective_pixel_count=n,
        id="room",
        _segments=[("hue", 0, n - 1, False)],
        _config={"mapping": "span"},
        group_size=1,
        rows=1,
    )
    ledfx = MagicMock()
    ledfx.devices.get.return_value = SimpleNamespace(
        pixel_positions=positions, pixel_count=n
    )
    return virtual, ledfx


def render_at(effect, t):
    """Render up to t in frames of at most half a second, like a frame loop."""
    while effect.now < t - 0.5:
        effect.now += 0.5
        effect.render()
    effect.now = t
    effect.render()
    return np.copy(effect.pixels)


def levels(pixels):
    return pixels.max(axis=1) / 255.0


def same(pixel, colour):
    return np.allclose(pixel, colour, atol=2)


# ------------------------------------------------------------- layout


def test_ring_layout_puts_the_first_lamp_at_the_front():
    effect = make_effect(pixel_count=8)
    assert effect._source == "ring"
    assert effect._angles[0] == pytest.approx(0.0)
    assert effect._angles[2] == pytest.approx(0.25)
    assert effect._angles[4] == pytest.approx(0.5)
    assert effect._angles[6] == pytest.approx(0.75)


def test_device_positions_are_taken_from_the_virtual():
    virtual, ledfx = fake_room([[0, 1, 0], [1, 0, 0], [0, -1, 0], [-1, 0, 0]])
    effect = make_effect(virtual=virtual, ledfx=ledfx, layout="Auto")
    assert effect._source == "device"
    assert np.allclose(effect._angles, [0.0, 0.25, 0.5, 0.75])


def test_strips_fall_back_to_zones_around_a_ring():
    effect = make_effect(pixel_count=100, layout="Auto")
    assert effect._source == "ring"
    assert effect._zone_count == 8
    assert np.allclose(np.sort(effect._angles), np.arange(8) / 8)
    pixels = render_at(effect, 0.5)
    assert pixels.shape == (100, 3)
    # The pixels of one zone share a colour
    assert np.allclose(pixels[0], pixels[5])


def test_matrix_keeps_one_lamp_per_pixel_on_a_grid():
    virtual = SimpleNamespace(effective_pixel_count=64, id="matrix", rows=8)
    effect = make_effect(virtual=virtual, layout="Auto")
    assert effect._source == "grid"
    assert effect._zone_count == 64


def test_zones_setting_splits_a_strip():
    effect = make_effect(pixel_count=60, zones=6)
    assert effect._zone_count == 6
    assert len(effect._angles) == 6


def test_layout_change_re_resolves_positions():
    effect = make_effect(pixel_count=5, layout="Ring")
    render_at(effect, 1.5)
    effect.update_config({"layout": "Line"})
    assert effect._source == "line"
    assert np.allclose(effect._plane_positions[:, 0], np.linspace(-1, 1, 5))
    assert effect._phase == 0.0


def test_mode_change_resets_the_state_but_keeps_the_lamps():
    effect = make_effect(pixel_count=8, mode="swirl")
    render_at(effect, 2.0)
    assert effect._phase > 0
    positions = effect._plane_positions.copy()
    effect.update_config({"mode": "beacon"})
    assert effect.mode == "beacon"
    assert effect._phase == 0.0
    assert np.array_equal(effect._plane_positions, positions)


def test_sector_change_rebuilds_the_channels_without_a_reset():
    effect = make_effect(pixel_count=8, mode="corners", sectors=2)
    render_at(effect, 2.0)
    effect.update_config({"sectors": 4})
    assert effect._channel_count == 4
    assert effect._phase > 0


def test_sectors_above_the_lamp_count_are_clamped():
    corners = make_effect(pixel_count=3, mode="corners", sectors=8)
    assert corners._channel_count == 3
    assert set(corners._channels.tolist()) == {0, 1, 2}
    scatter = make_effect(pixel_count=3, mode="scatter", sectors=8)
    assert len(scatter._cluster_lamps) == 3
    beacon = make_effect(pixel_count=3, mode="beacon", sectors=8)
    assert np.isfinite(render_at(beacon, 0.3)).all()


def test_plane_picks_the_turning_axes():
    # A wall of lamps: x across, z up, all at the same y
    wall = [[0, 1, 1], [1, 1, 0], [0, 1, -1], [-1, 1, 0]]
    virtual, ledfx = fake_room(wall)
    floor = make_effect(
        virtual=virtual, ledfx=ledfx, layout="Auto", plane="floor"
    )
    front = make_effect(
        virtual=virtual, ledfx=ledfx, layout="Auto", plane="front wall"
    )
    # Seen from above the wall is a line, seen from the front it is a ring
    assert np.allclose(front._angles, [0.0, 0.25, 0.5, 0.75])
    assert floor._angles[0] == pytest.approx(floor._angles[2])
    assert np.isfinite(render_at(floor, 0.5)).all()

    side_wall = [[1, 0, 1], [1, 1, 0], [1, 0, -1], [1, -1, 0]]
    virtual, ledfx = fake_room(side_wall)
    side = make_effect(
        virtual=virtual, ledfx=ledfx, layout="Auto", plane="side wall"
    )
    assert np.allclose(side._angles, [0.0, 0.25, 0.5, 0.75])


def test_a_lamp_at_the_centre_rides_with_the_pattern():
    room = [[0, 1, 0], [1, 0, 0], [0, -1, 0], [-1, 0, 0], [0, 0, 0]]
    virtual, ledfx = fake_room(room)
    effect = make_effect(
        virtual=virtual, ledfx=ledfx, layout="Auto", mode="swirl"
    )
    assert effect._centre[4]
    assert same(render_at(effect, 0.0)[4], RED)
    assert same(render_at(effect, 1.0)[4], RED)
    assert np.isfinite(effect.pixels).all()


# -------------------------------------------------------------- swirl


def test_swirl_front_lamp_shows_the_palette_start():
    effect = make_effect(pixel_count=8, mode="swirl")
    pixels = render_at(effect, 0.0)
    assert same(pixels[0], RED)
    assert same(pixels[2], GREEN)
    assert same(pixels[4], BLUE)
    assert same(pixels[6], WHITE)


def test_swirl_turns_a_quarter_in_a_quarter_of_the_turn():
    effect = make_effect(pixel_count=8, mode="swirl", beats_per_turn=4)
    render_at(effect, 0.0)
    # One beat of four: a quarter turn clockwise
    pixels = render_at(effect, 1.0)
    assert same(pixels[2], RED)
    assert same(pixels[4], GREEN)
    assert same(pixels[0], WHITE)


def test_swirl_counter_spin_turns_the_other_way():
    effect = make_effect(pixel_count=8, mode="swirl", spin="counter")
    render_at(effect, 0.0)
    pixels = render_at(effect, 1.0)
    assert same(pixels[6], RED)
    assert same(pixels[0], GREEN)


def test_swirl_sectors_repeat_the_palette():
    effect = make_effect(pixel_count=8, mode="swirl", sectors=2)
    pixels = render_at(effect, 0.0)
    assert same(pixels[0], RED) and same(pixels[4], RED)
    assert same(pixels[2], BLUE) and same(pixels[6], BLUE)


def test_swirl_softness_darkens_the_trough():
    hard = make_effect(pixel_count=8, mode="swirl", softness=0.0)
    soft = make_effect(pixel_count=8, mode="swirl", softness=1.0)
    assert np.allclose(levels(render_at(hard, 0.0)), 1.0)
    lit = levels(render_at(soft, 0.0))
    assert lit[0] == pytest.approx(1.0)
    assert lit[2] == pytest.approx(0.5)
    assert lit[4] == pytest.approx(0.0, abs=1e-6)


def test_beats_per_turn_sets_the_turn_time():
    effect = make_effect(pixel_count=8, mode="swirl", beats_per_turn=2)
    render_at(effect, 0.0)
    assert same(render_at(effect, 1.0)[4], RED)
    assert same(render_at(effect, 2.0)[0], RED)


def test_alternate_spin_reverses_every_turn():
    effect = make_effect(
        pixel_count=8, mode="swirl", spin="alternate", beats_per_turn=1
    )
    render_at(effect, 0.5)
    assert effect._direction == 1.0
    render_at(effect, 1.0)
    assert effect._direction == -1.0
    render_at(effect, 2.0)
    assert effect._direction == 1.0


# ------------------------------------------------------------- beacon


def test_beacon_lobe_is_bright_at_its_centre_and_dark_at_its_edges():
    effect = make_effect(pixel_count=8, mode="beacon", sectors=1, softness=1)
    lit = levels(render_at(effect, 0.0))
    assert lit[0] == pytest.approx(1.0)
    assert lit[1] == pytest.approx(0.5)
    assert lit[7] == pytest.approx(0.5)
    assert lit[2] == pytest.approx(0.0, abs=1e-6)
    assert lit[4] == pytest.approx(0.0, abs=1e-6)


def test_beacon_hard_edge_makes_a_block_half_a_turn_wide():
    effect = make_effect(
        pixel_count=16, mode="beacon", sectors=1, softness=0.0
    )
    lit = levels(render_at(effect, 0.0))
    block = np.isin(np.arange(16), [0, 1, 2, 3, 13, 14, 15])
    assert np.array_equal(lit > 0.5, block)


def test_beacon_two_lobes_light_opposite_sides():
    effect = make_effect(pixel_count=8, mode="beacon", sectors=2, softness=1)
    lit = levels(render_at(effect, 0.0))
    assert lit[0] == pytest.approx(1.0) and lit[4] == pytest.approx(1.0)
    assert lit[2] == pytest.approx(0.0, abs=1e-6)
    assert lit[6] == pytest.approx(0.0, abs=1e-6)


def test_beacon_colour_drifts_against_the_turn():
    effect = make_effect(pixel_count=8, mode="beacon", sectors=1, softness=1)
    assert same(render_at(effect, 0.0)[0], RED)
    # Half a turn later the lobe sits on the back lamp. Without drift it
    # would show that angle's palette colour (blue); the colour field has
    # turned the other way by three quarters of the turn, so it is white
    pixels = render_at(effect, 2.0)
    assert levels(pixels)[4] == pytest.approx(1.0)
    assert same(pixels[4], WHITE)


def test_background_lifts_the_beacon_gaps_in_their_field_colour():
    effect = make_effect(
        pixel_count=8,
        mode="beacon",
        sectors=1,
        softness=1.0,
        background=0.2,
        beats_per_turn=64,
    )
    pixels = render_at(effect, 0.0)
    assert same(pixels[4], BLUE * 0.2)
    assert same(pixels[0], RED)


# ------------------------------------------------------------ sectors


def test_sectors_show_hard_palette_wedges():
    effect = make_effect(pixel_count=8, mode="sectors", sectors=4)
    pixels = render_at(effect, 0.0)
    expected = [RED, RED, GREEN, GREEN, BLUE, BLUE, WHITE, WHITE]
    for pixel, colour in zip(pixels, expected):
        assert same(pixel, colour)


def test_sectors_at_full_softness_are_a_smooth_swirl():
    wedges = make_effect(
        pixel_count=8, mode="sectors", sectors=4, softness=1.0, gradient=SMOOTH
    )
    swirl = make_effect(
        pixel_count=8, mode="swirl", softness=0.0, gradient=SMOOTH
    )
    assert np.allclose(render_at(wedges, 0.3), render_at(swirl, 0.3), atol=2)


# ------------------------------------------------------- wave / ripple


def test_wave_flows_along_the_heading():
    effect = make_effect(
        pixel_count=5, layout="Line", mode="wave", heading=90, wavelength=1.0
    )
    pixels = render_at(effect, 0.0)
    for pixel, colour in zip(pixels, [RED, GREEN, BLUE, WHITE, RED]):
        assert same(pixel, colour)
    # A quarter cycle later the pattern has moved one lamp along the heading
    pixels = render_at(effect, 1.0)
    for pixel, colour in zip(pixels, [WHITE, RED, GREEN, BLUE, WHITE]):
        assert same(pixel, colour)


def test_wave_heading_selects_the_axis():
    effect = make_effect(pixel_count=8, mode="wave", heading=90, wavelength=1)
    pixels = render_at(effect, 0.0)
    assert same(pixels[6], RED)
    assert same(pixels[0], BLUE)


def test_wave_wavelength_stretches_the_palette():
    effect = make_effect(
        pixel_count=5, layout="Line", mode="wave", heading=90, wavelength=4.0
    )
    pixels = render_at(effect, 0.0)
    # A quarter of the palette across the room: red at one end, green at the other
    assert same(pixels[0], RED) and same(pixels[4], GREEN)


def test_wave_softness_darkens_the_trough():
    effect = make_effect(
        pixel_count=5, layout="Line", mode="wave", heading=90, softness=1.0
    )
    lit = levels(render_at(effect, 0.0))
    assert lit[0] == pytest.approx(1.0)
    assert lit[2] == pytest.approx(0.0, abs=1e-6)


def test_ripple_runs_outward_or_inward_by_spin():
    outward = make_effect(pixel_count=5, layout="Line", mode="ripple")
    inward = make_effect(
        pixel_count=5, layout="Line", mode="ripple", spin="counter"
    )
    start = render_at(outward, 0.0)
    assert same(start[2], RED) and same(start[1], BLUE)
    assert same(start[0], RED)
    # A quarter cycle later the colour at half radius came from the centre
    # side (outward) or from the edge side (inward)
    assert same(render_at(outward, 1.0)[1], GREEN)
    render_at(inward, 0.0)
    assert same(render_at(inward, 1.0)[1], WHITE)


# -------------------------------------------------------------- sweep


def test_sweep_front_crosses_the_room_over_one_step():
    effect = make_effect(
        pixel_count=5,
        layout="Line",
        mode="sweep",
        heading=90,
        heading_step=0,
        color_step=0.25,
    )
    assert all(same(pixel, RED) for pixel in render_at(effect, 0.01))
    half = render_at(effect, 0.5)
    assert same(half[0], GREEN) and same(half[1], GREEN)
    assert same(half[2], RED) and same(half[4], RED)
    # The next step starts with the room fully flooded and a new colour
    assert all(same(pixel, GREEN) for pixel in render_at(effect, 1.0))
    later = render_at(effect, 1.5)
    assert same(later[0], BLUE) and same(later[3], GREEN)


def test_sweep_heading_step_turns_the_next_front():
    effect = make_effect(
        pixel_count=5,
        layout="Line",
        mode="sweep",
        heading=90,
        heading_step=180,
        color_step=0.25,
    )
    render_at(effect, 0.5)
    assert effect._heading_offset == 0.0
    render_at(effect, 1.0)
    assert effect._heading_offset == 180.0
    # The second front comes from the right
    later = render_at(effect, 1.5)
    assert same(later[4], BLUE) and same(later[3], BLUE)
    assert same(later[0], GREEN)


def test_sweep_softness_widens_the_front():
    effect = make_effect(
        pixel_count=5,
        layout="Line",
        mode="sweep",
        heading=90,
        heading_step=0,
        softness=1.0,
        gradient=SMOOTH,
        color_step=0.5,
    )
    pixels = render_at(effect, 0.5)
    # Half way through the step the front reaches the middle lamp and the
    # lamp behind it is a mix of the old and the new colour
    assert pixels[2][2] == 0
    assert 0 < pixels[1][2] < pixels[0][2]
    assert same(pixels[4], RED)


def test_sweep_picks_random_colours_when_color_step_is_zero():
    effect = make_effect(pixel_count=4, mode="sweep", color_step=0.0)
    seen = []
    for t in (0.0, 1.0, 2.0, 3.0, 4.0):
        render_at(effect, t)
        seen.append((effect._sweep_old, effect._sweep_new))
    for old, new in seen:
        jump = (new - old) % 1.0
        assert 0.15 - 1e-9 <= jump <= 0.85 + 1e-9
    assert len({round(new, 6) for _, new in seen}) > 1


# ------------------------------------------------------------- halves


def test_halves_split_the_room_in_two_colours():
    effect = make_effect(
        pixel_count=8,
        mode="halves",
        heading=0,
        heading_step=90,
        color_step=0.25,
    )
    pixels = render_at(effect, 0.5)
    # The first event moved the palette point to green; the far side
    # shows the colour half a palette on, white
    for lamp in (7, 0, 1, 2, 6):
        assert same(pixels[lamp], GREEN)
    for lamp in (3, 4, 5):
        assert same(pixels[lamp], WHITE)


def test_halves_turn_a_quarter_per_step():
    effect = make_effect(
        pixel_count=8,
        mode="halves",
        heading=0,
        heading_step=90,
        color_step=0.25,
    )
    render_at(effect, 0.5)
    pixels = render_at(effect, 1.0)
    # Second event: heading 90, the palette point on the right, its
    # opposite colour on the left
    for lamp in (0, 1, 2, 3, 4):
        assert same(pixels[lamp], BLUE)
    for lamp in (5, 6, 7):
        assert same(pixels[lamp], RED)


def test_halves_turn_smoothly_when_heading_step_is_zero():
    effect = make_effect(
        pixel_count=8,
        mode="halves",
        heading=0,
        heading_step=0,
        color_step=0.25,
    )
    render_at(effect, 0.0)
    # An eighth of a turn: the split faces lamp 1
    pixels = render_at(effect, 0.5)
    assert same(pixels[1], GREEN) and same(pixels[5], WHITE)
    pixels = render_at(effect, 1.0)
    assert same(pixels[2], BLUE) and same(pixels[6], RED)


def test_halves_softness_blends_across_the_room():
    effect = make_effect(
        pixel_count=5,
        layout="Line",
        mode="halves",
        heading=90,
        heading_step=0,
        softness=1.0,
        color_step=0.25,
        gradient=SMOOTH,
    )
    pixels = render_at(effect, 0.0)
    assert pixels[0][2] > pixels[2][2] > pixels[4][2]


# ------------------------------------------------------------ corners


def test_corner_channels_are_balanced_around_the_room():
    effect = make_effect(pixel_count=8, mode="corners", sectors=4)
    assert effect._channel_count == 4
    assert np.array_equal(np.bincount(effect._channels), [2, 2, 2, 2])
    for channel in range(4):
        members = np.where(effect._channels == channel)[0]
        assert (members[1] - members[0]) % 8 in (1, 7)


def test_heading_turns_the_corner_channels():
    effect = make_effect(pixel_count=8, mode="corners", sectors=2, heading=90)
    channels = effect._channels
    # Right / left anchors turned a quarter clockwise become back / front
    assert channels[0] == channels[1] == channels[7]
    assert channels[3] == channels[4] == channels[5]
    assert channels[0] != channels[4]


def test_corners_light_the_next_channel_every_step():
    effect = make_effect(pixel_count=8, mode="corners", sectors=4)
    lit = [
        levels(render_at(effect, t)) > 0.5 for t in (0.5, 1.0, 2.0, 3.0, 4.0)
    ]
    assert lit[0].sum() == 2
    for channel in range(4):
        assert np.array_equal(lit[channel], effect._channels == channel)
    assert np.array_equal(lit[4], lit[0])


def test_corners_hold_then_fade_by_softness():
    effect = make_effect(
        pixel_count=8, mode="corners", sectors=4, softness=0.5
    )
    assert levels(render_at(effect, 0.25)).max() == pytest.approx(1.0)
    assert levels(render_at(effect, 0.75)).max() == pytest.approx(0.5)
    assert levels(render_at(effect, 0.99)).max() == pytest.approx(
        0.02, abs=0.01
    )


def test_corners_random_spin_never_repeats_a_channel():
    effect = make_effect(
        pixel_count=8, mode="corners", sectors=4, spin="random"
    )
    channels = [effect._channel]
    for t in range(1, 30):
        render_at(effect, float(t))
        channels.append(effect._channel)
    assert all(a != b for a, b in zip(channels, channels[1:]))
    assert set(channels) == {0, 1, 2, 3}


def test_corners_alternate_spin_bounces_between_the_ends():
    effect = make_effect(
        pixel_count=8, mode="corners", sectors=4, spin="alternate"
    )
    channels = [effect._channel]
    for t in range(1, 8):
        render_at(effect, float(t))
        channels.append(effect._channel)
    assert channels == [0, 1, 2, 3, 2, 1, 0, 1]


def test_unlit_lamps_show_the_field_colour_dimmed():
    effect = make_effect(
        pixel_count=8,
        mode="corners",
        sectors=4,
        background=0.4,
        beats_per_turn=64,
    )
    pixels = render_at(effect, 0.5)
    unlit = effect._channels != 0
    assert np.allclose(levels(pixels)[unlit], 0.4, atol=0.01)
    assert same(pixels[4], BLUE * 0.4)


# -------------------------------------------------------------- noise


def test_noise_is_deterministic_per_seed_and_drifts():
    first = make_effect(pixel_count=8, mode="noise", gradient=SMOOTH)
    second = make_effect(pixel_count=8, mode="noise", gradient=SMOOTH)
    start = render_at(first, 0.0)
    assert np.array_equal(start, render_at(second, 0.0))
    assert not np.array_equal(start, render_at(first, 2.0))
    third = make_effect(pixel_count=8, mode="noise", gradient=SMOOTH)
    rebase(third, seed=8)
    assert not np.array_equal(start, render_at(third, 0.0))


def test_noise_terraces_with_sectors():
    effect = make_effect(pixel_count=16, mode="noise", sectors=4)
    for pixel in render_at(effect, 0.3):
        assert any(same(pixel, colour) for colour in (RED, GREEN, BLUE, WHITE))
    smooth = make_effect(
        pixel_count=16, mode="noise", sectors=1, gradient=SMOOTH
    )
    pixels = render_at(smooth, 0.3)
    assert np.any((pixels[:, 0] > 20) & (pixels[:, 2] > 20))


def test_noise_samples_the_third_axis():
    corners = ((0, 1), (1, 0), (0, -1), (-1, 0))
    flat = [[x, y, 0.0] for x, y in corners]
    tall = [[x, y, z] for (x, y), z in zip(corners, (1, -1, 1, -1))]
    outputs = []
    for room in (flat, tall):
        virtual, ledfx = fake_room(room)
        effect = make_effect(
            virtual=virtual,
            ledfx=ledfx,
            layout="Auto",
            mode="noise",
            gradient=SMOOTH,
        )
        outputs.append(render_at(effect, 0.0))
    assert not np.array_equal(outputs[0], outputs[1])


# ------------------------------------------------------------ scatter


def test_scatter_lights_lamps_within_the_radius_only():
    effect = make_effect(
        pixel_count=9, layout="Line", mode="scatter", sectors=1, radius=0.3
    )
    pixels = render_at(effect, 0.5)
    centre = effect._space[effect._cluster_lamps[0]]
    distance = np.linalg.norm(effect._space - centre, axis=1)
    lit = levels(pixels) > 0
    assert np.array_equal(lit, distance < 0.3)
    assert 2 <= lit.sum() <= 3
    assert levels(pixels)[effect._cluster_lamps[0]] == pytest.approx(1.0)


def test_scatter_picks_new_clusters_every_step():
    effect = make_effect(
        pixel_count=9, layout="Line", mode="scatter", sectors=2, radius=0.3
    )
    seen = [tuple(effect._cluster_lamps)]
    for t in range(1, 6):
        render_at(effect, float(t))
        seen.append(tuple(effect._cluster_lamps))
    for before, after in zip(seen, seen[1:]):
        assert not set(before) & set(after)
    assert all(len(set(lamps)) == 2 for lamps in seen)


def test_scatter_clusters_fade_by_softness():
    effect = make_effect(
        pixel_count=9, layout="Line", mode="scatter", radius=0.3, softness=1.0
    )
    assert levels(render_at(effect, 0.25)).max() == pytest.approx(0.75)
    assert levels(render_at(effect, 0.75)).max() == pytest.approx(0.25)


def test_scatter_clusters_reach_in_three_dimensions():
    # Two lamps stacked at the centre a floor apart, two at the sides
    room = [[0, 0, 1], [0, 0, -1], [1, 0, 0], [-1, 0, 0]]
    virtual, ledfx = fake_room(room)
    effect = make_effect(
        virtual=virtual,
        ledfx=ledfx,
        layout="Auto",
        mode="scatter",
        sectors=1,
        radius=1.5,
    )
    lit = levels(render_at(effect, 0.5)) > 0
    centre = effect._cluster_lamps[0]
    distance = np.linalg.norm(effect._space - effect._space[centre], axis=1)
    assert np.array_equal(lit, distance < 1.5)
    assert lit.sum() == 3
    # The lamp straight above or below, or straight across, stays dark:
    # seen only from above it would sit on top of the centre
    opposite = {0: 1, 1: 0, 2: 3, 3: 2}
    assert not lit[opposite[centre]]


# ----------------------------------------------------- level and safety


def test_reactive_depth_scales_the_brightness_with_the_band_level():
    effect = make_effect(pixel_count=4, mode="swirl", reactive_depth=0.5)
    effect._band.level = 0.0
    assert np.allclose(levels(render_at(effect, 0.1)), 0.5)
    effect._band.level = 1.0
    assert np.allclose(levels(render_at(effect, 0.2)), 1.0)


def test_audio_updates_feed_the_band_level():
    effect = make_effect(pixel_count=4, band="Bass", sensitivity=2.0)
    frame = np.zeros(len(FREQS))
    frame[FREQS < 250] = 0.5
    data = MagicMock()
    data.melbanks.melbanks = [frame]
    data.melbanks.melbank_processors = [
        SimpleNamespace(melbank_frequencies=FREQS)
    ]
    for _ in range(20):
        effect.audio_data_updated(data)
    assert effect._band.level > 0.5


def test_flash_limiter_holds_a_lamp_that_flashes_too_fast():
    effect = make_effect(
        pixel_count=4,
        mode="beacon",
        sectors=1,
        beats_per_turn=1,
        timer_bpm=240,
        flash_limit=True,
    )
    # A turn every 0.25 s: the front lamp would flash four times a second
    assert levels(render_at(effect, 0.0))[0] == pytest.approx(1.0)
    assert levels(render_at(effect, 0.125))[0] == pytest.approx(0.0)
    assert levels(render_at(effect, 0.25))[0] == pytest.approx(0.0)
    assert levels(render_at(effect, 0.5))[0] == pytest.approx(1.0)


# --------------------------------------------------------------- auto


def test_auto_mode_rotates_through_the_modes():
    effect = make_effect(pixel_count=8, mode="auto", auto_steps=2)
    modes = [effect.mode]
    for t in range(1, 21):
        render_at(effect, float(t))
        modes.append(effect.mode)
    assert all(mode in OrbitEffect.AUTO_MODES for mode in modes)
    assert len(set(modes)) > 2
    for i in range(1, 21):
        if i % 2 == 1:
            assert modes[i] != modes[i - 1]
        else:
            assert modes[i] == modes[i - 1]


@pytest.mark.parametrize("mode", OrbitEffect.AUTO_MODES)
@pytest.mark.parametrize(
    "layout,pixel_count",
    [("Ring", 1), ("Ring", 8), ("Line", 5), ("Grid", 9), ("Ring", 100)],
)
def test_every_mode_renders_in_range(mode, layout, pixel_count):
    effect = make_effect(
        pixel_count=pixel_count,
        layout=layout,
        mode=mode,
        sectors=3,
        softness=0.5,
        background=0.2,
        spin="alternate",
    )
    for t in (0.0, 0.4, 1.0, 1.7, 3.0, 9.0):
        pixels = render_at(effect, t)
        assert pixels.shape == (pixel_count, 3)
        assert np.isfinite(pixels).all()
        assert pixels.min() >= 0 and pixels.max() <= 255


# ------------------------------------------------------------ sections


def audio_data(level, phase=0.0):
    """Audio data with a flat melbank at the given level."""
    data = MagicMock()
    data.melbanks.melbanks = [np.full(len(FREQS), level)]
    data.melbanks.melbank_processors = [
        SimpleNamespace(melbank_frequencies=FREQS)
    ]
    data.bar_oscillator = lambda: phase
    data.bpm_beat_now = lambda: False
    data.volume_beat_now = lambda: False
    data.onset = lambda: False
    return data


def feed_sections(effect, level, seconds, start):
    """Feed a flat level for a while at 50 Hz, returns the end time."""
    t = start
    for _ in range(int(seconds * 50)):
        t += 0.02
        effect._sections.update(level, t)
    return t


def test_auto_sections_pick_hard_modes_when_loud():
    effect = make_effect(pixel_count=8, mode="auto", auto_steps=1)
    feed_sections(effect, 1.0, 3.0, 0.0)
    assert effect._sections.section == "loud"
    modes = set()
    for t in range(4, 30):
        render_at(effect, float(t))
        modes.add(effect.mode)
    assert modes <= set(OrbitEffect.AUTO_LOUD_MODES)
    assert len(modes) > 2


def test_auto_sections_pick_soft_modes_when_quiet():
    effect = make_effect(pixel_count=8, mode="auto", auto_steps=1)
    assert effect._sections.section == "quiet"
    modes = set()
    for t in range(1, 30):
        render_at(effect, float(t))
        modes.add(effect.mode)
    assert modes <= set(OrbitEffect.AUTO_QUIET_MODES)


def test_auto_sections_switch_on_a_drop():
    effect = make_effect(pixel_count=8, mode="auto", auto_steps=64)
    render_at(effect, 0.5)
    quiet_mode = effect.mode
    assert quiet_mode in OrbitEffect.AUTO_QUIET_MODES
    # A long quiet build, then the music comes back loud
    t = feed_sections(effect, 0.02, 6.0, 0.0)
    for _ in range(5):
        t += 0.02
        effect.audio_data_updated(audio_data(1.0))
        effect._sections.update(1.0, t)
        if effect._sections.drop:
            effect._drop_pending = True
    assert effect._drop_pending
    render_at(effect, 7.0)
    assert effect.mode in OrbitEffect.AUTO_LOUD_MODES
    assert effect.mode != quiet_mode
    assert not effect._drop_pending


def test_audio_updates_feed_the_sections_in_auto_mode():
    effect = make_effect(pixel_count=4, mode="auto")
    effect._sections._last_time = 0.0
    for _ in range(60):
        effect.audio_data_updated(audio_data(0.8, phase=1.0))
    assert effect._sections.level > 0.5


def test_palette_shift_moves_the_palette():
    effect = make_effect(pixel_count=4, mode="swirl")
    plain = effect._palette(np.array([0.5]))[0]
    effect._palette_shift = 0.5
    assert effect._palette(np.array([0.0]))[0].tolist() == plain.tolist()
    # A mode change resets the shift
    effect.update_config({"mode": "wave"})
    assert effect._palette_shift == 0.0


def test_auto_sections_off_rotates_blindly():
    effect = make_effect(
        pixel_count=8, mode="auto", auto_steps=1, auto_sections=False
    )
    for _ in range(60):
        effect.audio_data_updated(audio_data(1.0))
    # The detector is not fed, and the choice comes from every mode
    assert effect._sections.section == "quiet"
    modes = set()
    for t in range(1, 40):
        render_at(effect, float(t))
        modes.add(effect.mode)
    assert modes & set(OrbitEffect.AUTO_LOUD_MODES)
    assert modes & set(OrbitEffect.AUTO_QUIET_MODES)
