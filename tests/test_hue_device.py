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


# Channels of a music area as the bridge reports them: a Play tube whose
# last segments share channel 3 with the first TV segment, a TV strip
# whose last segment shares channel 1 with the tube's first, a kitchen
# strip sharing channel 5 with the middle of the TV, a window strip
# sharing channel 7, and six plain bulbs.
MUSIC_AREA_MEMBERS = {
    "0": [["go", 0]],
    "1": [["play", 0], ["tv", 6]],
    "2": [["play", 1], ["play", 2], ["play", 3]],
    "3": [["play", 4], ["play", 5], ["play", 6], ["tv", 0]],
    "4": [["tv", 1]],
    "5": [["tv", 2], ["kitchen", 3], ["kitchen", 4], ["kitchen", 5]],
    "6": [["tv", 3]],
    "7": [["tv", 4], ["window", 0], ["window", 1], ["window", 2]],
    "8": [["tv", 5]],
    "9": [["couch", 0]],
    "10": [["kitchen", 0], ["kitchen", 1], ["kitchen", 2]],
    "11": [["worktop", 0]],
    "12": [["cupboard", 0]],
    "13": [["table", 0]],
    "14": [["window", 4], ["window", 5], ["window", 6]],
    "15": [["printer", 0]],
}
MUSIC_AREA_LIGHTS = {str(i): [0.0, 0.0, 0.0] for i in range(16)}


def test_along_the_strips_chains_strips_through_shared_channels():
    order = HueDevice.order_along_strips(
        MUSIC_AREA_LIGHTS, MUSIC_AREA_MEMBERS, list(range(16))
    )
    # Tube 1, 2, 3 runs straight into the TV 3, 4, 5, 6, 7, 8, then the
    # rest of the kitchen and window strips, then the bulbs in room order
    assert order[:8] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert order[8:10] == [10, 14]
    assert order[10:] == [0, 9, 11, 12, 13, 15]
    assert sorted(order) == list(range(16))


def test_along_the_strips_keeps_segment_order_within_a_strip():
    members = {
        "0": [["strip", 3]],
        "1": [["strip", 0], ["strip", 1]],
        "2": [["strip", 2]],
        "3": [["bulb", 0]],
    }
    lights = {str(i): [0.0, 0.0, 0.0] for i in range(4)}
    assert HueDevice.order_along_strips(lights, members, [3, 0, 1, 2]) == [
        1,
        2,
        0,
        3,
    ]


def test_along_the_strips_orients_a_strip_towards_the_previous_one():
    # Two separate strips: the second starts at whichever end sits closer
    # to the end of the first in room order
    members = {
        "0": [["a", 0]],
        "1": [["a", 1]],
        "2": [["b", 1]],
        "3": [["b", 0]],
    }
    lights = {str(i): [0.0, 0.0, 0.0] for i in range(4)}
    assert HueDevice.order_along_strips(lights, members, [0, 1, 2, 3]) == [
        0,
        1,
        2,
        3,
    ]


def test_along_the_strips_without_members_is_the_room_order():
    lights = {str(i): [0.0, 0.0, 0.0] for i in range(3)}
    assert HueDevice.order_along_strips(lights, {}, [2, 0, 1]) == [2, 0, 1]


def test_apply_channel_order_uses_the_members_for_along_the_strips():
    device = HueDevice.__new__(HueDevice)
    device._config = {
        "name": "test",
        "channel_order": "Along the strips",
        "pixel_lights": MUSIC_AREA_LIGHTS,
        "pixel_members": MUSIC_AREA_MEMBERS,
    }
    device._apply_channel_order()
    assert device._channel_ids[:8] == [1, 2, 3, 4, 5, 6, 7, 8]


def test_lights_from_entertainment_group_reads_positions_and_members():
    device = HueDevice.__new__(HueDevice)
    device._config = {"ip_address": "bridge", "username": "u"}
    device._hue_request = lambda *args, **kwargs: (
        {
            "data": [
                {
                    "channels": [
                        {
                            "channel_id": 0,
                            "position": {"x": 0.1, "y": 0.2, "z": 0.3},
                            "members": [
                                {
                                    "service": {
                                        "rid": "tv",
                                        "rtype": "entertainment",
                                    },
                                    "index": 0,
                                },
                                {
                                    "service": {
                                        "rid": "tv",
                                        "rtype": "entertainment",
                                    },
                                    "index": 1,
                                },
                            ],
                        },
                        {
                            "channel_id": 1,
                            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
                        },
                    ]
                }
            ]
        },
        {},
    )
    lights, members = device._lights_from_entertainment_group("area")
    assert lights == {"0": [0.1, 0.2, 0.3], "1": [0.0, 0.0, 0.0]}
    assert members == {"0": [["tv", 0], ["tv", 1]], "1": []}


def test_pixel_positions_follow_the_channel_order():
    device = HueDevice.__new__(HueDevice)
    device._config = {
        "name": "test",
        "pixel_count": 3,
        "channel_order": "Left to right",
        "pixel_lights": {
            "0": [1.0, 0.0, 0.5],
            "1": [-1.0, 0.0, 0.5],
            "2": [0.0, 1.0, 0.5],
        },
    }
    device._apply_channel_order()
    assert device._channel_ids == [1, 2, 0]
    assert device.pixel_positions == [
        [-1.0, 0.0, 0.5],
        [0.0, 1.0, 0.5],
        [1.0, 0.0, 0.5],
    ]


def test_pixel_positions_default_to_channel_id_order():
    device = HueDevice.__new__(HueDevice)
    device._config = {
        "name": "test",
        "pixel_count": 2,
        "pixel_lights": {"0": [0.0, 1.0, 0.0], "1": [0.0, -1.0, 0.0]},
    }
    device._channel_ids = None
    assert device.pixel_positions == [[0.0, 1.0, 0.0], [0.0, -1.0, 0.0]]


def test_pixel_positions_are_unknown_before_the_zone_is_read():
    device = HueDevice.__new__(HueDevice)
    device._config = {"name": "test", "pixel_count": 2}
    device._channel_ids = None
    assert device.pixel_positions is None
