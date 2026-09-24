"""Unit tests for the pure helpers of the Philips Hue device."""

import pytest

from ledfx.devices.hue import CHANNEL_ORDERS, HueDevice

# A four light room in Hue coordinates: x left(-1) to right(1),
# y back(-1) to front(1), z floor(-1) to ceiling(1). Channel ids are
# deliberately out of spatial order, as the Hue app assigns them in the
# order lights were added to the zone.
ROOM = {
    "0": [1.0, 0.0, 0.0],  # right
    "1": [0.0, -1.0, 0.5],  # back, higher up
    "2": [-1.0, 0.0, -0.5],  # left, lower down
    "3": [0.0, 1.0, 0.0],  # front
}
RIGHT, BACK, LEFT, FRONT = 0, 1, 2, 3


def test_hue_app_order_is_channel_id_order():
    assert HueDevice.order_channels(ROOM, "Hue app") == [0, 1, 2, 3]


def test_around_the_room_goes_clockwise_from_the_left():
    assert HueDevice.order_channels(ROOM, "Around the room") == [
        LEFT,
        FRONT,
        RIGHT,
        BACK,
    ]


def test_around_the_room_ignores_height():
    tall = {k: [x, y, z * 3] for k, (x, y, z) in ROOM.items()}
    assert HueDevice.order_channels(
        tall, "Around the room"
    ) == HueDevice.order_channels(ROOM, "Around the room")


def test_around_the_room_uses_the_zone_centre():
    # Same room shifted into one corner of the coordinate space
    shifted = {
        k: [x * 0.2 + 0.7, y * 0.2 + 0.7, z] for k, (x, y, z) in ROOM.items()
    }
    assert HueDevice.order_channels(shifted, "Around the room") == [
        LEFT,
        FRONT,
        RIGHT,
        BACK,
    ]


def test_left_to_right_sorts_on_x():
    assert HueDevice.order_channels(ROOM, "Left to right") == [
        LEFT,
        BACK,
        FRONT,
        RIGHT,
    ]


def test_front_to_back_sorts_on_y():
    assert HueDevice.order_channels(ROOM, "Front to back") == [
        FRONT,
        RIGHT,
        LEFT,
        BACK,
    ]


def test_bottom_to_top_sorts_on_z():
    assert HueDevice.order_channels(ROOM, "Bottom to top") == [
        LEFT,
        RIGHT,
        FRONT,
        BACK,
    ]


@pytest.mark.parametrize("order", CHANNEL_ORDERS)
def test_lights_at_the_same_position_keep_channel_id_order(order):
    stacked = {"2": [0, 0, 0], "0": [0, 0, 0], "1": [0, 0, 0]}
    assert HueDevice.order_channels(stacked, order) == [0, 1, 2]


@pytest.mark.parametrize("order", CHANNEL_ORDERS)
def test_every_order_is_a_permutation(order):
    assert sorted(HueDevice.order_channels(ROOM, order)) == [0, 1, 2, 3]


def test_empty_zone():
    assert HueDevice.order_channels({}, "Around the room") == []


def test_build_frame_layout():
    frame = HueDevice.build_frame("abc", [(255, 0, 16)])
    header = b"HueStream" + bytes([2, 0, 0, 0, 0, 0, 0]) + b"abc"
    assert frame[: len(header)] == header
    # channel id, then 16 bit big endian red, green, blue
    assert frame[len(header) :] == bytes([0, 255, 255, 0, 0, 16, 16])


def test_build_frame_maps_pixels_to_channels():
    frame = HueDevice.build_frame(
        "id", [(1, 2, 3), (4, 5, 6)], channel_ids=[7, 3]
    )
    body = frame[len(b"HueStream") + 7 + len("id") :]
    assert body == bytes([7, 1, 1, 2, 2, 3, 3, 3, 4, 4, 5, 5, 6, 6])


def test_build_frame_clamps_and_truncates_floats():
    frame = HueDevice.build_frame("id", [(300.0, -5.0, 12.9)])
    body = frame[len(b"HueStream") + 7 + len("id") :]
    assert body == bytes([0, 255, 255, 0, 0, 12, 12])


def test_response_errors_reads_clip_v2_errors():
    assert HueDevice._response_errors({"errors": [], "data": []}) == []
    assert HueDevice._response_errors(
        {"errors": [{"description": "busy"}, {"type": 3}], "data": []}
    ) == ["busy", "{'type': 3}"]
    assert HueDevice._response_errors([{"success": {}}]) == []
