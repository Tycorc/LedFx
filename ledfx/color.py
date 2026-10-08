import itertools
import logging
from collections import namedtuple

import numpy as np
from numpy.typing import NDArray
from PIL import ImageColor

_LOGGER = logging.getLogger(__name__)
RGBA = namedtuple("RGBA", ("red", "green", "blue", "alpha"), defaults=(255,))
RGB = namedtuple("RGB", ("red", "green", "blue"))


class Gradient:
    """Represents a gradient with a list of colors and a mode."""

    __slots__ = "angle", "colors", "mode"

    @classmethod
    def from_string(cls, gradient_str: str):
        """Parse CSS-style mode(angle, color position%, ...) gradient strings."""
        gradient_str = LEDFX_GRADIENTS.get(gradient_str, gradient_str)
        mode, angle_colors = gradient_str.split("(", 1)
        mode.strip("-gradient")
        angle, colors = angle_colors.strip(")").split(",", 1)
        angle = int(angle.strip("deg"))
        colors = colors.split("%")
        colors = [color.strip(", ").rsplit(" ", 1) for color in colors if color.strip()]
        colors = [
            (parse_color(color), float(position) / 100.0) for color, position in colors
        ]
        colors.sort(key=lambda tup: tup[1])

        return cls(colors, mode, angle)

    def __init__(self, colors, mode="linear", angle="90"):
        self.colors = colors
        self.mode = mode
        self.angle = angle

    def sample(self, position: float) -> str:
        """Return a hex color string sampled from this Gradient at a normalized
        position in [0.0, 1.0].
        """
        pos = max(0.0, min(1.0, float(position)))

        stops = list(self.colors)
        stops.sort(key=lambda c: c[1])

        first_color, first_pos = stops[0]
        last_color, last_pos = stops[-1]
        if pos <= first_pos:
            return (
                f"#{first_color.red:02x}{first_color.green:02x}{first_color.blue:02x}"
            )
        if pos >= last_pos:
            return f"#{last_color.red:02x}{last_color.green:02x}{last_color.blue:02x}"

        for (c1, p1), (c2, p2) in itertools.pairwise(stops):
            if p1 <= pos <= p2:
                t = 0.0 if p2 == p1 else (pos - p1) / (p2 - p1)
                r = int(round(c1.red + (c2.red - c1.red) * t))  # noqa: RUF046
                g = int(round(c1.green + (c2.green - c1.green) * t))  # noqa: RUF046
                b = int(round(c1.blue + (c2.blue - c1.blue) * t))  # noqa: RUF046
                return f"#{r:02x}{g:02x}{b:02x}"

        return "#000000"


def hsv_to_rgb(hue: NDArray, saturation: float, value: float) -> NDArray:
    """Convert hues and saturation/value in 0..1 to RGB values in 0..255."""

    hue_i = hue * 6

    i = np.floor(hue_i).astype(int)

    f = hue_i - i

    p = value * (1 - saturation)
    q = value * (1 - saturation * f)
    t = value * (1 - saturation * (1 - f))

    i = i % 6

    rgb = np.empty((hue.shape[0], 3))

    # Select the same sector values without broadcasting six alternatives per
    # channel through np.choose. This matters for large Rainbow pixel arrays;
    # keep the arithmetic above unchanged to preserve RGB rounding.
    rgb[:, 0] = np.where(
        (i == 0) | (i == 5), value, np.where(i == 1, q, np.where(i == 4, t, p))
    )
    rgb[:, 1] = np.where(
        (i == 1) | (i == 2), value, np.where(i == 3, q, np.where(i == 0, t, p))
    )
    rgb[:, 2] = np.where(
        (i == 3) | (i == 4), value, np.where(i == 5, q, np.where(i == 2, t, p))
    )

    rgb *= 255
    return rgb


def hsv_to_rgb_vect(h, s, v, out=None):
    """h, s, v: float32 arrays (N,) in [0,1] Returns float32 RGB in [0,255]. If `out`
    (N,3) float32 is provided, writes in-place.
    """
    h = np.asarray(h, dtype=np.float32)
    s = np.asarray(s, dtype=np.float32)
    v = np.asarray(v, dtype=np.float32)

    N = h.shape[0]
    if out is None:
        out = np.empty((N, 3), dtype=np.float32)

    r = out[:, 0]
    g = out[:, 1]
    b = out[:, 2]

    h6 = (h * 6.0).astype(np.float32)
    i = np.floor(h6).astype(np.int32)  # sector 0..5
    f = h6 - i

    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))

    m0 = i == 0
    r[m0] = v[m0]
    g[m0] = t[m0]
    b[m0] = p[m0]
    m1 = i == 1
    r[m1] = q[m1]
    g[m1] = v[m1]
    b[m1] = p[m1]
    m2 = i == 2
    r[m2] = p[m2]
    g[m2] = v[m2]
    b[m2] = t[m2]
    m3 = i == 3
    r[m3] = p[m3]
    g[m3] = q[m3]
    b[m3] = v[m3]
    m4 = i == 4
    r[m4] = t[m4]
    g[m4] = p[m4]
    b[m4] = v[m4]
    m5 = i >= 5
    r[m5] = v[m5]
    g[m5] = p[m5]
    b[m5] = q[m5]

    out *= 255.0
    return out


def rgb_to_hsv_vect(rgb, out=None):
    """rgb: (N,3) or (3,) uint8/float; returns float32 HSV in [0,1]. If `out` (N,3)
    float32 is provided, writes in-place.
    """
    arr = np.asarray(rgb, dtype=np.float32)
    scalar = arr.ndim == 1
    if scalar:
        arr = arr[np.newaxis, :]

    arr = arr / 255.0
    r, g, b = arr[:, 0], arr[:, 1], arr[:, 2]

    maxc = np.maximum(np.maximum(r, g), b)
    minc = np.minimum(np.minimum(r, g), b)
    delta = maxc - minc

    if out is None:
        out = np.empty((arr.shape[0], 3), dtype=np.float32)
    h = out[:, 0]
    s = out[:, 1]
    v = out[:, 2]

    v[:] = maxc

    s[:] = 0.0
    nz = maxc != 0.0
    s[nz] = delta[nz] / maxc[nz]

    h[:] = 0.0
    mask = delta > 0.0
    r_eq = (maxc == r) & mask
    g_eq = (maxc == g) & mask
    b_eq = (maxc == b) & mask

    h[r_eq] = ((g[r_eq] - b[r_eq]) / delta[r_eq]) % 6.0
    h[g_eq] = ((b[g_eq] - r[g_eq]) / delta[g_eq]) + 2.0
    h[b_eq] = ((r[b_eq] - g[b_eq]) / delta[b_eq]) + 4.0

    h[:] = (h / 6.0) % 1.0
    return out[0] if scalar else out


def parse_color(color: str | list[int] | tuple[int, ...]) -> RGB:
    """Parses a color value and returns an RGB object."""
    # A list or tuple is [r, g, b] (alpha removed): refuse a channel that is
    # not an int in 0..255 rather than format it into a malformed hex.
    if isinstance(color, (list, tuple)):
        if len(color) != 3 or not all(type(c) is int and 0 <= c <= 255 for c in color):
            msg = f"colour channels must be integers from 0 to 255, got {list(color)}"
            raise ValueError(msg)
        return RGB(*color)
    try:
        if not isinstance(color, str):
            raise ValueError  # noqa: TRY004
        if color in LEDFX_COLORS:
            color = LEDFX_COLORS[color]
        if color.startswith("#"):
            color = color.strip("#")
            return RGB(*int(color, 16).to_bytes(3, "big"))
        return RGB(*ImageColor.getrgb(color))
    # OverflowError: a hex value too long for three bytes (#1000000).
    except (ValueError, AssertionError, OverflowError):
        msg = f"Invalid color: {color}"
        raise ValueError(msg)


def parse_gradient(gradient: str):
    """
    Parse a gradient string and return the corresponding gradient object.

    The gradient can be either a color or a full gradient. The function tries to parse
    the gradient using the `Gradient.from_string` and `parse_color` functions. If
    successful, it returns the parsed gradient object. If parsing fails, a warning
    is logged and a `ValueError` is raised.

    Args:
        gradient (str): The gradient string to parse.

    Returns:
        Gradient: The parsed gradient object.

    Raises:
        ValueError: If the gradient string is invalid.
    """
    for func in Gradient.from_string, parse_color:
        try:
            return func(gradient)
        except Exception:  # noqa: BLE001, S112
            continue
    msg = f"Invalid gradient: {gradient}"
    _LOGGER.warning(msg)
    raise ValueError(msg)


def validate_color(color: str) -> str:
    """
    Validates and formats a color.

    Args:
        color: A color name or hex string.

    Returns:
        str: The validated and formatted color string.

    """
    if isinstance(color, str):
        return coerce_color(color)
    raise ValueError(f"Invalid color: {color}")


def coerce_color(value: object) -> str:
    """
    Formats a color given as a name, a hex string or an [r, g, b] list or
    tuple. This is the lenient form for config loading and v1; requests
    use validate_color, which takes only a string.

    Raises:
        ValueError: If value is not a color.
    """
    if isinstance(value, (str, list, tuple)):
        return "#{:02x}{:02x}{:02x}".format(*parse_color(value))
    raise ValueError(f"Invalid color: {value}")


def get_color_at_position(gradient_like, position: float) -> str:
    """Accepts a Gradient instance, an inline gradient string, or a simple color
    string and returns a hex color sampled at `position` (0.0..1.0).
    """
    if isinstance(gradient_like, Gradient):
        return gradient_like.sample(position)

    try:
        parsed = parse_gradient(gradient_like)
    except Exception:  # noqa: BLE001
        return coerce_color(gradient_like)

    if isinstance(parsed, RGB):
        return "#{:02x}{:02x}{:02x}".format(*parsed)

    return parsed.sample(position)


def validate_gradient(gradient: str) -> str:
    """Validates the given gradient string."""
    parse_gradient(gradient)
    return gradient


def resolve_gradient(value: str, gradients_collection) -> tuple[str, Gradient | None]:
    """Return (config_string, parsed_gradient_or_None); reject invalid inline
    gradients.
    """
    trimmed = value.strip()

    defaults, user_vals = gradients_collection.get_all()
    raw_gradient = user_vals.get(trimmed) or defaults.get(trimmed)

    if raw_gradient:
        config_string = raw_gradient
    else:
        validate_gradient(trimmed)
        config_string = trimmed

    parsed = None
    try:
        parsed = gradients_collection[trimmed]
    except Exception:  # noqa: BLE001
        try:
            parsed = parse_gradient(trimmed)
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to parse gradient %s: %s", trimmed, e)
            parsed = None

    return config_string, parsed


COLOR_GROUPS = [
    {
        "value": 0.0,
        "keys": [
            "lows_color",
            "color_lows",
            "color_low",
            "low_band",
            "color_beat",
            "color_min",
            "color",
        ],
    },
    {
        "value": 0.5,
        "keys": [
            "color_mid",
            "color_mids",
            "mid_band",
            "mids_color",
            "hit_color",
            "color_scan",
            "color_bar",
            "text_color",
        ],
    },
    {
        "value": 1.0,
        "keys": [
            "color_high",
            "high_band",
            "high_color",
            "sparks_color",
            "strobe_color",
            "color_max",
        ],
    },
    {
        "value": None,
        "keys": [
            "flash_color",
            "pixel_color",
            "color_peak",
        ],
    },
]


def build_gradient_config(
    gradient_input: str,
    gradients_collection,
    skip_keys: set | None = None,
) -> dict:
    """Resolve gradient/color groups into config while preserving explicit skip_keys."""
    config_val, parsed_gradient = resolve_gradient(gradient_input, gradients_collection)
    config_updates: dict = {"gradient": config_val}

    if parsed_gradient is not None:
        for group in COLOR_GROUPS:
            if group["value"] is None:
                continue
            try:
                color_at_pos = get_color_at_position(parsed_gradient, group["value"])
            except Exception as exc:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to sample gradient at %s: %s",
                    group["value"],
                    exc,
                )
                continue
            for color_key in group["keys"]:
                if skip_keys and color_key in skip_keys:
                    continue
                config_updates[color_key] = color_at_pos

    return config_updates


LEDFX_COLORS = {
    "red": "#ff0000",
    "orange-deep": "#ff2800",
    "orange": "#ff7800",
    "yellow": "#ffc800",
    "yellow-acid": "#a0ff00",
    "green": "#00ff00",
    "green-forest": "#228b22",
    "green-spring": "#00ff7f",
    "green-teal": "#008080",
    "green-turquoise": "#00c78c",
    "green-coral": "#00ff32",
    "cyan": "#00ffff",
    "blue": "#0000ff",
    "blue-light": "#4169e1",
    "blue-navy": "#000080",
    "blue-aqua": "#00ffff",
    "purple": "#800080",
    "pink": "#ff00b2",
    "magenta": "#ff00ff",
    "black": "#000000",
    "white": "#ffffff",
    "gold": "#ffd700",
    "hotpink": "#ff69b4",
    "lightblue": "#add8e6",
    "lightgreen": "#98fb98",
    "lightpink": "#ffb6c1",
    "lightyellow": "#ffffe0",
    "maroon": "#800000",
    "mint": "#bdfcc9",
    "olive": "#556b2f",
    "peach": "#ff6464",
    "plum": "#dda0dd",
    "sepia": "#5e2612",
    "skyblue": "#87ceeb",
    "steelblue": "#4682b4",
    "tan": "#d2b48c",
    "violetred": "#d02090",
}

LEDFX_GRADIENTS = {
    "Rainbow": "linear-gradient(90deg, rgb(255, 0, 0) 0%, rgb(255, 120, 0) 14%, rgb(255, 200, 0) 28%, rgb(0, 255, 0) 42%, rgb(0, 199, 140) 56%, rgb(0, 0, 255) 70%, rgb(128, 0, 128) 84%, rgb(255, 0, 178) 98%)",
    "Dancefloor": "linear-gradient(90deg, rgb(255, 0, 0) 0%, rgb(255, 0, 178) 50%, rgb(0, 0, 255) 100%)",
    "Plasma": "linear-gradient(90deg, rgb(0, 0, 255) 0%, rgb(128, 0, 128) 25%, rgb(255, 0, 0) 50%, rgb(255, 40, 0) 75%, rgb(255, 200, 0) 100%)",
    "Ocean": "linear-gradient(90deg, rgb(0, 255, 255) 0%, rgb(0, 0, 255) 100%)",
    "Viridis": "linear-gradient(90deg, rgb(128, 0, 128) 0%, rgb(0, 0, 255) 25%, rgb(0, 128, 128) 50%, rgb(0, 255, 0) 75%, rgb(255, 200, 0) 100%)",
    "Jungle": "linear-gradient(90deg, rgb(0, 255, 0) 0%, rgb(34, 139, 34) 50%, rgb(255, 120, 0) 100%)",
    "Spring": "linear-gradient(90deg, rgb(255, 0, 178) 0%, rgb(255, 40, 0) 50%, rgb(255, 200, 0) 100%)",
    "Winter": "linear-gradient(90deg, rgb(0, 199, 140) 0%, rgb(0, 255, 50) 100%)",
    "Frost": "linear-gradient(90deg, rgb(0, 0, 255) 0%, rgb(0, 255, 255) 33%, rgb(128, 0, 128) 66%, rgb(255, 0, 178) 99%)",
    "Sunset": "linear-gradient(90deg, rgb(0, 0, 128) 0%, rgb(255, 120, 0) 50%, rgb(255, 0, 0) 100%)",
    "Borealis": "linear-gradient(90deg, rgb(255, 40, 0) 0%, rgb(128, 0, 128) 33%, rgb(0, 199, 140) 66%, rgb(0, 255, 0) 99%)",
    "Rust": "linear-gradient(90deg, rgb(255, 40, 0) 0%, rgb(255, 0, 0) 100%)",
    "Winamp": "linear-gradient(90deg, rgb(0, 255, 0) 0%, rgb(255, 200, 0) 25%, rgb(255, 120, 0) 50%, rgb(255, 40, 0) 75%, rgb(255, 0, 0) 100%)",
}
