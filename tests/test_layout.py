"""Unit tests for the room layout helper used by the spatial effects."""

from types import SimpleNamespace

import numpy as np
import pytest

from ledfx.effects.utils.layout import (
    LAYOUTS,
    anchors,
    angles,
    assign_channels,
    device_positions,
    grid_positions,
    line_positions,
    normalise,
    project,
    radii,
    resolve_positions,
    ring_positions,
    virtual_positions,
    zone_positions,
)

# Four lamps in the corners of a room, clockwise from the front left
CORNERS = np.array(
    [
        [-1.0, 1.0, 0.0],
        [1.0, 1.0, 0.0],
        [1.0, -1.0, 0.0],
        [-1.0, -1.0, 0.0],
    ]
)


class FakeDevice:
    def __init__(self, positions):
        self.pixel_positions = positions
        self.pixel_count = len(positions) if positions is not None else 0


class FakeVirtual:
    def __init__(self, segments, mapping="span", group_size=1, rows=1):
        self._segments = segments
        self._config = {"mapping": mapping}
        self.group_size = group_size
        self.rows = rows
        total = sum(end - start + 1 for _, start, end, _ in segments)
        self.effective_pixel_count = int(np.ceil(total / group_size))


def ledfx_with(devices):
    return SimpleNamespace(devices=devices)


# ----------------------------------------------------------- synthetic


def test_ring_starts_at_the_front_and_runs_clockwise():
    ring = ring_positions(4)
    assert ring[0] == pytest.approx([0.0, 1.0, 0.0])
    assert ring[1] == pytest.approx([1.0, 0.0, 0.0])
    assert ring[2] == pytest.approx([0.0, -1.0, 0.0])
    assert ring[3] == pytest.approx([-1.0, 0.0, 0.0])


def test_line_runs_left_to_right():
    line = line_positions(3)
    assert line[:, 0].tolist() == [-1.0, 0.0, 1.0]
    assert not line[:, 1:].any()
    assert line_positions(1).tolist() == [[0.0, 0.0, 0.0]]


def test_grid_has_row_zero_at_the_front():
    grid = grid_positions(6, rows=2)
    assert grid[0] == pytest.approx([-1.0, 1.0, 0.0])
    assert grid[2] == pytest.approx([1.0, 1.0, 0.0])
    assert grid[3] == pytest.approx([-1.0, -1.0, 0.0])
    assert grid[5] == pytest.approx([1.0, -1.0, 0.0])


def test_grid_clamps_rows_to_the_pixel_count():
    assert grid_positions(2, rows=8).shape == (2, 3)


# ------------------------------------------------------------- devices


def test_device_positions_need_one_per_pixel():
    assert device_positions(FakeDevice(None)) is None
    device = FakeDevice([[0, 0, 0], [1, 1, 1]])
    device.pixel_count = 3
    assert device_positions(device) is None
    device.pixel_count = 2
    assert device_positions(device).shape == (2, 3)


def test_device_positions_ignore_a_broken_property():
    class Broken:
        pixel_count = 1

        @property
        def pixel_positions(self):
            raise RuntimeError("no bridge")

    assert device_positions(Broken()) is None


def test_virtual_positions_follow_the_segments():
    devices = {
        "hue": FakeDevice(CORNERS.tolist()),
        "bulb": FakeDevice([[0.0, 0.0, 1.0]]),
    }
    virtual = FakeVirtual(
        [["hue", 1, 3, False], ["bulb", 0, 0, False], ["hue", 0, 0, False]]
    )
    positions = virtual_positions(virtual, ledfx_with(devices))
    assert positions.shape == (5, 3)
    assert positions[0].tolist() == CORNERS[1].tolist()
    assert positions[3].tolist() == [0.0, 0.0, 1.0]
    assert positions[4].tolist() == CORNERS[0].tolist()


def test_virtual_positions_honour_inverted_segments():
    devices = {"hue": FakeDevice(CORNERS.tolist())}
    virtual = FakeVirtual([["hue", 0, 3, True]])
    positions = virtual_positions(virtual, ledfx_with(devices))
    assert positions[0].tolist() == CORNERS[3].tolist()
    assert positions[3].tolist() == CORNERS[0].tolist()


def test_virtual_positions_average_pixel_groups():
    devices = {"hue": FakeDevice(CORNERS.tolist())}
    virtual = FakeVirtual([["hue", 0, 3, False]], group_size=2)
    positions = virtual_positions(virtual, ledfx_with(devices))
    assert positions.shape == (2, 3)
    assert positions[0] == pytest.approx([0.0, 1.0, 0.0])
    assert positions[1] == pytest.approx([0.0, -1.0, 0.0])


def test_virtual_positions_use_the_first_segment_in_copy_mode():
    devices = {"hue": FakeDevice(CORNERS.tolist())}
    virtual = FakeVirtual(
        [["hue", 0, 3, False], ["hue", 0, 3, False]], mapping="copy"
    )
    virtual.effective_pixel_count = 4
    positions = virtual_positions(virtual, ledfx_with(devices))
    assert positions.shape == (4, 3)


def test_virtual_positions_are_unknown_when_a_device_has_none():
    devices = {
        "hue": FakeDevice(CORNERS.tolist()),
        "wled": FakeDevice(None),
    }
    devices["wled"].pixel_count = 4
    virtual = FakeVirtual([["hue", 0, 3, False], ["wled", 0, 3, False]])
    assert virtual_positions(virtual, ledfx_with(devices)) is None
    assert virtual_positions(SimpleNamespace(), ledfx_with(devices)) is None
    virtual = FakeVirtual([["gone", 0, 3, False]])
    assert virtual_positions(virtual, ledfx_with(devices)) is None


# ------------------------------------------------------------- resolve


def test_resolve_auto_prefers_the_device_positions():
    devices = {"hue": FakeDevice(CORNERS.tolist())}
    virtual = FakeVirtual([["hue", 0, 3, False]])
    positions, source = resolve_positions(
        "Auto", 4, virtual, ledfx_with(devices)
    )
    assert source == "device"
    assert positions.tolist() == CORNERS.tolist()


def test_resolve_auto_falls_back_to_a_ring_or_grid():
    positions, source = resolve_positions("Auto", 6)
    assert source == "ring"
    assert positions.shape == (6, 3)
    virtual = FakeVirtual([["wled", 0, 5, False]], rows=2)
    positions, source = resolve_positions(
        "Auto", 6, virtual, ledfx_with({"wled": FakeDevice(None)})
    )
    assert source == "grid"
    assert positions[0][1] == 1.0 and positions[5][1] == -1.0


def test_resolve_explicit_layouts():
    for layout in LAYOUTS:
        positions, source = resolve_positions(layout, 9)
        assert positions.shape == (9, 3)
        assert source in ("ring", "line", "grid")
    positions, source = resolve_positions("Grid", 9)
    assert source == "grid"
    # 9 pixels without a matrix virtual make a 3 x 3 grid
    assert sorted(set(positions[:, 1].tolist())) == [-1.0, 0.0, 1.0]
    _, source = resolve_positions("Line", 3)
    assert source == "line"


# --------------------------------------------------------------- maths


def test_zone_positions_average_their_pixels():
    zone_of_pixel = np.array([0, 0, 1, 1])
    zones = zone_positions(CORNERS, zone_of_pixel, 2)
    assert zones[0] == pytest.approx([0.0, 1.0, 0.0])
    assert zones[1] == pytest.approx([0.0, -1.0, 0.0])


def test_normalise_centres_and_scales_the_room():
    positions = np.array([[0.0, 0.0, 2.0], [1.0, 0.0, 2.0], [0.5, 0.5, 4.0]])
    room = normalise(positions)
    assert room.mean(axis=0) == pytest.approx([0.0, 0.0, 0.0])
    assert np.max(np.abs(room[:, :2])) == pytest.approx(1.0)
    assert np.max(np.abs(room[:, 2])) == pytest.approx(1.0)
    assert not normalise(np.zeros((3, 3))).any()
    assert normalise(np.zeros((0, 3))).shape == (0, 3)


def test_angles_run_clockwise_from_the_front():
    ring = ring_positions(8)
    assert angles(ring) == pytest.approx(np.arange(8) / 8)
    assert angles(np.array([[0.0, 1.0, 0.0]]))[0] == pytest.approx(0.0)
    assert angles(np.array([[1.0, 0.0, 0.0]]))[0] == pytest.approx(0.25)
    assert angles(np.array([[-1.0, 0.0, 0.0]]))[0] == pytest.approx(0.75)


def test_radii_scale_the_farthest_lamp_to_one():
    positions = np.array([[0.0, 0.0, 0.0], [0.5, 0.0, 0.0], [0.0, 2.0, 0.0]])
    assert radii(positions) == pytest.approx([0.0, 0.25, 1.0])
    assert radii(np.zeros((2, 3))).tolist() == [0.0, 0.0]


def test_project_measures_along_the_heading():
    assert project(CORNERS, 0) == pytest.approx([1.0, 1.0, -1.0, -1.0])
    assert project(CORNERS, 90) == pytest.approx([-1.0, 1.0, 1.0, -1.0])
    assert project(CORNERS, 180) == pytest.approx([-1.0, -1.0, 1.0, 1.0])


def test_anchors_are_symmetric_about_the_front_axis():
    assert anchors(1).tolist() == [[0.0, 0.0, 0.0]]
    two = anchors(2)
    assert two[0] == pytest.approx([1.0, 0.0, 0.0])
    assert two[1] == pytest.approx([-1.0, 0.0, 0.0])
    four = anchors(4)
    assert four[0] == pytest.approx([np.sqrt(0.5), np.sqrt(0.5), 0.0])
    assert four[3] == pytest.approx([-np.sqrt(0.5), np.sqrt(0.5), 0.0])


def test_assign_channels_picks_the_nearest_lamps():
    channels = assign_channels(CORNERS, anchors(4))
    # Corner anchors run front right, back right, back left, front left
    assert channels.tolist() == [3, 0, 1, 2]


def test_assign_channels_stays_balanced():
    # All six lamps on the right, two channels: the left channel must
    # still get its fair half
    positions = np.array([[1.0, y, 0.0] for y in np.linspace(-1, 1, 6)])
    channels = assign_channels(positions, anchors(2))
    assert sorted(channels.tolist()) == [0, 0, 0, 1, 1, 1]
    # Seven lamps over two channels: one channel takes the spare lamp
    positions = np.array([[1.0, y, 0.0] for y in np.linspace(-1, 1, 7)])
    counts = np.bincount(assign_channels(positions, anchors(2)))
    assert sorted(counts.tolist()) == [3, 4]


def test_assign_channels_edge_cases():
    assert assign_channels(np.zeros((0, 3)), anchors(2)).tolist() == []
    assert assign_channels(CORNERS, anchors(1)).tolist() == [0, 0, 0, 0]
    assert assign_channels(CORNERS, np.zeros((0, 3))).tolist() == [-1] * 4
    # More channels than lamps: every lamp still gets a channel
    channels = assign_channels(CORNERS[:2], anchors(4))
    assert (channels >= 0).all()
