"""
Where every pixel of a virtual stands in the room.

Lamp based devices know where their lamps are: a Hue entertainment zone
stores the x, y, z of every channel as placed in the Hue app, from -1 to 1
with x left to right, y back to front and z floor to ceiling. The spatial
effects colour every lamp by that position instead of by its number, so a
gradient strip flows along its length, the two ends of a room can be told
apart and a colour field can turn around the room as one.

Devices that know no positions get a synthetic layout: a ring around the
room, a line, or a grid for a matrix. The helpers here turn positions into
the quantities the effects work with: the angle around the room, the
distance from the centre, the position along a heading, and balanced
channels around a set of anchor points.
"""

import math

import numpy as np

LAYOUTS = ["Auto", "Ring", "Line", "Grid"]


def ring_positions(count):
    """count lamps evenly around a circle, clockwise from the front."""
    count = max(1, int(count))
    turns = np.arange(count) / count
    positions = np.zeros((count, 3))
    positions[:, 0] = np.sin(turns * 2 * math.pi)
    positions[:, 1] = np.cos(turns * 2 * math.pi)
    return positions


def line_positions(count):
    """count lamps in a line from left to right."""
    count = max(1, int(count))
    positions = np.zeros((count, 3))
    if count > 1:
        positions[:, 0] = np.linspace(-1.0, 1.0, count)
    return positions


def grid_positions(count, rows):
    """count lamps on a grid of rows, row 0 at the front, left to right."""
    count = max(1, int(count))
    rows = max(1, min(int(rows), count))
    columns = int(math.ceil(count / rows))
    index = np.arange(count)
    row = index // columns
    column = index % columns
    positions = np.zeros((count, 3))
    if columns > 1:
        positions[:, 0] = -1.0 + 2.0 * column / (columns - 1)
    if rows > 1:
        positions[:, 1] = 1.0 - 2.0 * row / (rows - 1)
    return positions


def device_positions(device):
    """
    The positions of a device's pixels as an (n, 3) array, or None.

    A device that knows where its pixels are exposes a pixel_positions
    property with one [x, y, z] per pixel in pixel order.
    """
    try:
        positions = getattr(device, "pixel_positions", None)
    except Exception:
        return None
    if positions is None:
        return None
    try:
        positions = np.asarray(positions, dtype=float)
    except (TypeError, ValueError):
        # Ragged or non numeric positions are as good as none
        return None
    if positions.ndim != 2 or positions.shape[1] != 3 or len(positions) == 0:
        return None
    if len(positions) != device.pixel_count:
        return None
    return positions


def zone_map(pixel_count, zones, auto_limit=32, auto_count=8):
    """
    Split pixel_count pixels into zones (lamps).

    Returns the zone count and the zone of every pixel. zones <= 0 is
    automatic: one zone per pixel up to auto_limit pixels, auto_count
    zones for longer outputs such as strips.
    """
    pixel_count = int(pixel_count)
    zones = int(zones)
    if zones <= 0:
        zones = pixel_count if pixel_count <= auto_limit else auto_count
    zones = max(1, min(zones, pixel_count))
    return zones, (np.arange(pixel_count) * zones) // pixel_count


def virtual_positions(virtual, ledfx):
    """
    The positions of every effective pixel of a virtual, or None.

    Walks the virtual's segments in order and asks every device for its
    pixel positions. Any device without positions makes the whole virtual
    unknown, so the caller falls back to a synthetic layout.
    """
    segments = getattr(virtual, "_segments", None)
    devices = getattr(ledfx, "devices", None)
    if not segments or devices is None:
        return None

    try:
        mapping = virtual._config.get("mapping", "span")
    except Exception:
        mapping = "span"
    if mapping == "copy":
        segments = segments[:1]

    parts = []
    for segment in segments:
        try:
            device_id, start, end, invert = segment
        except (TypeError, ValueError):
            return None
        device = devices.get(device_id)
        if device is None:
            return None
        positions = device_positions(device)
        if positions is None:
            return None
        part = positions[int(start) : int(end) + 1]
        if len(part) == 0:
            return None
        if invert:
            part = part[::-1]
        parts.append(part)
    positions = np.concatenate(parts)

    group_size = int(getattr(virtual, "group_size", 1) or 1)
    if group_size > 1:
        groups = int(math.ceil(len(positions) / group_size))
        positions = np.array(
            [
                positions[i * group_size : (i + 1) * group_size].mean(axis=0)
                for i in range(groups)
            ]
        )

    expected = getattr(virtual, "effective_pixel_count", len(positions))
    if len(positions) != expected:
        return None
    return positions


def synthetic_positions(layout, count, rows=1):
    """
    Positions for count pixels on a synthetic layout, plus their source.

    layout is one of LAYOUTS. Auto gives a grid for a matrix (rows > 1)
    and a ring otherwise, Grid without rows picks a square. The source
    is "ring", "line" or "grid".
    """
    count = max(1, int(count))
    rows = max(1, int(rows))
    if layout == "Line":
        return line_positions(count), "line"
    if layout == "Grid":
        if rows <= 1:
            rows = max(1, int(round(math.sqrt(count))))
        return grid_positions(count, rows), "grid"
    if layout == "Auto" and rows > 1 and count > rows:
        return grid_positions(count, rows), "grid"
    return ring_positions(count), "ring"


def resolve_positions(layout, count, virtual=None, ledfx=None):
    """
    Positions for count pixels as an (count, 3) array, plus their source.

    layout is one of LAYOUTS. Auto uses the device positions when every
    device of the virtual knows them, a grid for a matrix virtual, and a
    ring otherwise. The source is "device", "ring", "line" or "grid".
    """
    count = max(1, int(count))
    rows = 1
    if virtual is not None:
        try:
            rows = int(getattr(virtual, "rows", 1) or 1)
        except Exception:
            rows = 1

    if layout == "Auto" and virtual is not None and ledfx is not None:
        positions = virtual_positions(virtual, ledfx)
        if positions is not None and len(positions) == count:
            return positions, "device"
    return synthetic_positions(layout, count, rows)


def zone_positions(positions, zone_of_pixel, zone_count):
    """The mean position of the pixels of every zone, (zone_count, 3)."""
    positions = np.asarray(positions, dtype=float)
    zone_of_pixel = np.asarray(zone_of_pixel)
    zones = np.zeros((zone_count, 3))
    for zone in range(zone_count):
        members = positions[zone_of_pixel == zone]
        if len(members):
            zones[zone] = members.mean(axis=0)
    return zones


def normalise(positions):
    """
    Centre the positions on their mean and scale them into -1..1.

    x and y share one scale so the room keeps its shape, z is scaled on
    its own. Axes without any spread stay at 0.
    """
    positions = np.asarray(positions, dtype=float)
    if len(positions) == 0:
        return positions.reshape(0, 3)
    centred = positions - positions.mean(axis=0)
    flat = np.max(np.abs(centred[:, :2]))
    if flat > 1e-9:
        centred[:, :2] /= flat
    tall = np.max(np.abs(centred[:, 2]))
    if tall > 1e-9:
        centred[:, 2] /= tall
    return centred


def angles(positions):
    """
    Angle of every position around the centre, in turns from 0 to 1.

    0 is the front (positive y, the TV side), 0.25 the right, 0.5 the back
    and 0.75 the left: clockwise seen from above.
    """
    positions = np.asarray(positions, dtype=float)
    turn = (math.pi / 2 - np.arctan2(positions[:, 1], positions[:, 0])) / (
        2 * math.pi
    )
    return np.mod(turn, 1.0)


def radii(positions):
    """Distance of every position from the centre, scaled so the farthest is 1."""
    positions = np.asarray(positions, dtype=float)
    distance = np.hypot(positions[:, 0], positions[:, 1])
    farthest = distance.max() if len(distance) else 0.0
    if farthest > 1e-9:
        distance = distance / farthest
    return distance


def heading_vector(heading):
    """Unit vector for a heading in degrees, 0 towards the front, 90 to the right."""
    radians = math.radians(heading)
    return np.array([math.sin(radians), math.cos(radians)])


def project(positions, heading):
    """
    How far along a heading every position lies.

    heading is in degrees, 0 towards the front and 90 towards the right, so
    a wave with heading 0 travels from the back of the room to the front.
    """
    positions = np.asarray(positions, dtype=float)
    return positions[:, :2] @ heading_vector(heading)


def anchors(count):
    """
    count anchor points around the room.

    1 is the centre. 2 are right and left, 4 are the four corners, other
    counts are spread evenly around a circle so that the layout is
    symmetric about the front to back axis.
    """
    count = max(1, int(count))
    if count == 1:
        return np.zeros((1, 3))
    turns = (np.arange(count) + 0.5) / count
    points = np.zeros((count, 3))
    points[:, 0] = np.sin(turns * 2 * math.pi)
    points[:, 1] = np.cos(turns * 2 * math.pi)
    return points


def assign_channels(positions, anchor_points):
    """
    Split the positions into balanced channels around the anchor points.

    Every channel takes the lamps closest to its anchor, in turns, and no
    channel takes more than its fair share, so a room with all its lamps on
    one side still fills every channel. Returns the channel of every
    position.
    """
    positions = np.asarray(positions, dtype=float)
    anchor_points = np.asarray(anchor_points, dtype=float)
    count = len(positions)
    channels = len(anchor_points)
    assigned = np.full(count, -1, dtype=int)
    if count == 0 or channels == 0:
        return assigned
    if channels == 1:
        assigned[:] = 0
        return assigned

    share, spare = divmod(count, channels)
    sizes = np.zeros(channels, dtype=int)
    distances = np.linalg.norm(
        positions[:, None, :] - anchor_points[None, :, :], axis=2
    )
    remaining = count
    while remaining > 0:
        progressed = False
        for channel in range(channels):
            if sizes[channel] > share:
                continue
            if sizes[channel] == share:
                if spare <= 0:
                    continue
                spare -= 1
            free = np.where(assigned < 0)[0]
            if len(free) == 0:
                break
            pick = free[np.argmin(distances[free, channel])]
            assigned[pick] = channel
            sizes[channel] += 1
            remaining -= 1
            progressed = True
            if remaining == 0:
                break
        if not progressed:
            # Should not happen, but never spin: give the rest away in order
            for pick in np.where(assigned < 0)[0]:
                assigned[pick] = int(np.argmin(sizes))
                sizes[assigned[pick]] += 1
            break
    return assigned
