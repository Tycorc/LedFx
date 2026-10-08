import logging
import threading
import timeit
from functools import lru_cache
from typing import TYPE_CHECKING, ClassVar

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from ledfx.color import LEDFX_COLORS, hsv_to_rgb, parse_color
from ledfx.configuration.fields import X_LEGACY, X_OMIT_DEFAULT, CoercedFloat, Color
from ledfx.configuration.plugin import PluginConfig, TypedConfig
from ledfx.effects.utils.logsec_helper import LogSecHelper
from ledfx.events import EffectUpdatedEvent
from ledfx.utils import BaseRegistry, RegistryLoader

if TYPE_CHECKING:
    from ledfx.virtuals import Virtual

_LOGGER = logging.getLogger(__name__)


class DummyEffect:
    config = PluginConfig()
    _active = True
    is_active = _active
    NAME = name = ""
    logsec = None

    def __init__(self, pixel_count):
        self.pixels = np.zeros((pixel_count, 3))
        self.pixel_count = pixel_count

    def _render(self):
        self.render()

    def render(self):
        self.pixels = np.zeros((self.pixel_count, 3))

    def get_pixels(self):
        return self.pixels

    def activate(self):
        pass

    def _deactivate(self):
        self.deactivate()

    def deactivate(self):
        self.pixels = None  # Free the numpy array
        self._active = False
        self.is_active = False


def mix_colors(color_1: tuple, color_2: tuple, ratio: float) -> tuple:
    """Mixes two colors based on a given ratio."""
    if np.array_equal(color_2, []):
        return (
            color_1[0] * (1 - ratio) + 0,
            color_1[1] * (1 - ratio) + 0,
            color_1[2] * (1 - ratio) + 0,
        )
    else:
        return (
            color_1[0] * (1 - ratio) + color_2[0] * ratio,
            color_1[1] * (1 - ratio) + color_2[1] * ratio,
            color_1[2] * (1 - ratio) + color_2[2] * ratio,
        )


def fill_rainbow(pixels: NDArray, initial_hue: float, delta_hue: float) -> NDArray:
    """Fills the given pixels with a rainbow effect."""
    sat = 0.95
    val = 1.0

    hues = np.arange(initial_hue, initial_hue + len(pixels) * delta_hue, delta_hue)

    hues = hues[: len(pixels)]

    return hsv_to_rgb(hues, sat, val)


def blur_pixels(pixels: NDArray, sigma: float) -> NDArray:
    """Applies a blur effect to the given pixels."""
    rgb_array = pixels.T
    rgb_array[0] = smooth(rgb_array[0], sigma)
    rgb_array[1] = smooth(rgb_array[1], sigma)
    rgb_array[2] = smooth(rgb_array[2], sigma)
    return rgb_array.T


@lru_cache(maxsize=1024)
def _gaussian_kernel1d(sigma: float, order: int, array_len: int) -> NDArray:
    """Produces a 1D Gaussian or Gaussian-derivative filter kernel as a numpy array."""

    sigma = max(0.00001, sigma)
    radius = max(1, int(round(4.0 * sigma)))  # noqa: RUF046
    radius = min(int((array_len - 1) / 2), radius)
    radius = max(radius, 1)

    if order < 0:
        raise ValueError("Order must non-negative")
    if not (isinstance(radius, int) or radius.is_integer()) or radius <= 0:
        raise ValueError("Radius must a positive integer")

    p = np.polynomial.Polynomial([0, 0, -0.5 / (sigma * sigma)])
    x = np.arange(-radius, radius + 1)
    phi_x = np.exp(p(x), dtype=np.double)
    phi_x /= phi_x.sum()

    if order > 0:
        q = np.polynomial.Polynomial([1])
        p_deriv = p.deriv()
        for _ in range(order):
            q = q.deriv() + q * p_deriv
        phi_x *= q(x)

    return phi_x


def fast_blur_pixels(pixels: NDArray, sigma: float) -> NDArray:
    """Applies a fast blur effect to the given pixels using a Gaussian kernel."""
    if len(pixels) == 0:
        raise ValueError("Cannot smooth an empty array")
    kernel = _gaussian_kernel1d(sigma, 0, len(pixels))
    pixels[:, 0] = np.convolve(pixels[:, 0], kernel, mode="same")
    pixels[:, 1] = np.convolve(pixels[:, 1], kernel, mode="same")
    pixels[:, 2] = np.convolve(pixels[:, 2], kernel, mode="same")
    return pixels


def fast_blur_array(array: NDArray, sigma: float) -> NDArray:
    """Apply fast Gaussian blur to a 1-dimensional array."""
    if len(array) == 0:
        raise ValueError("Cannot smooth an empty array")
    kernel = _gaussian_kernel1d(sigma, 0, len(array))
    return np.convolve(array, kernel, mode="same")


def smooth(x, sigma):
    """Smooths a 1D array via a Gaussian filter."""

    if len(x) == 0:
        raise ValueError("Cannot smooth an empty array")

    kernel_radius = max(1, int(round(4.0 * sigma)))  # noqa: RUF046
    filter_kernel = _gaussian_kernel1d(sigma, 0, kernel_radius)

    extended_input_len = len(x) + len(filter_kernel) - 1
    x_mirrored = x
    while len(x_mirrored) < extended_input_len:
        mirror_len = min(len(x_mirrored), (extended_input_len - len(x_mirrored)) // 2)
        x_mirrored = np.r_[
            x_mirrored[mirror_len - 1 :: -1],
            x_mirrored,
            x_mirrored[-1 : -(mirror_len + 1) : -1],
        ]

    y = np.convolve(x_mirrored, filter_kernel, mode="valid")

    assert len(y) == len(x)

    return y


@BaseRegistry.no_registration
class Effect(BaseRegistry):
    """Manages an effect"""

    NAME = ""
    HIDDEN_KEYS = None
    ADVANCED_KEYS: ClassVar[list[str]] = ["diag"]
    PERMITTED_KEYS = None
    USES_MELBANK_RANGE = False
    _config = None
    _active = False
    _virtual: "Virtual | None" = None

    class Config(PluginConfig):
        blur: CoercedFloat = Field(
            0.0, description="Amount to blur the effect", ge=0.0, le=10
        )
        flip: bool = Field(False, description="Flip the effect")
        mirror: bool = Field(False, description="Mirror the effect")
        brightness: CoercedFloat = Field(
            1.0, description="Brightness of strip", ge=0.0, le=1.0
        )
        background_color: Color = Field(
            "#000000", description="Apply a background color"
        )
        background_brightness: CoercedFloat = Field(
            1.0, description="Brightness of the background color", ge=0.0, le=1.0
        )
        diag: bool = Field(False, description="Enable diagnostic logging")
        advanced: bool | None = Field(
            None,
            json_schema_extra={X_OMIT_DEFAULT: True, X_LEGACY: {"description": False}},
        )

    config = TypedConfig(Config)

    def __init__(self, ledfx, config):
        self._ledfx = ledfx
        self._config = None
        self.lock = threading.Lock()
        self.logsec = LogSecHelper(self)
        self.passed = 0.0
        self._last_frame_time = timeit.default_timer()
        self.now = self._last_frame_time
        self.background_mode = "additive"
        self.update_config(config)

    def __del__(self):
        if self._active:
            self._deactivate()

    def activate(self, virtual):
        """Attaches an output channel to the effect"""
        with self.lock:
            self._virtual = virtual
            self.pixels = np.zeros((virtual.effective_pixel_count, 3))
            valid_classes = list(type(self).__bases__)
            valid_classes.append(type(self))
            for base in valid_classes:
                if hasattr(base, "on_activate"):
                    base.on_activate(self, virtual.effective_pixel_count)
            self._active = True
            _LOGGER.info("Effect %s activated.", self.NAME)

    def _deactivate(self):
        with self.lock:
            self.deactivate()

    def deactivate(self):
        """Detaches an output channel from the effect"""
        self.pixels = None
        self._virtual = None  # Clear circular reference to allow garbage collection
        if self.logsec:
            self.logsec.effect = None
            self.logsec.diag = False
        self._active = False
        _LOGGER.info("Effect %s deactivated.", self.NAME)

    @classmethod
    def get_combined_default_schema(cls) -> dict[str, object]:
        return cls.config_model().model_validate({}).as_dict()

    def update_config(self, config):
        if isinstance(config, PluginConfig):
            config = config.as_dict()  # effects are created from a validated model
        with self.lock:
            if self._config is not None:
                config = self._config.as_dict() | config
            validated_config = type(self).config_model().model_validate(config)

            old_state, old_diag = dict(vars(self)), self.logsec.diag
            self._config = validated_config

            bg_color = parse_color(self.config.background_color)
            self.bg_color_use = bg_color != parse_color(LEDFX_COLORS["black"])

            self._bg_color = np.array(bg_color) * self.config.background_brightness
            self._bg_color_pil = tuple(
                int(c * self.config.background_brightness) for c in bg_color
            )

            self.flip = self.config.flip
            self.mirror = self.config.mirror
            self.brightness = self.config.brightness
            self.logsec.diag = self.config.diag

            def inherited(cls, method):
                if hasattr(cls, method) and hasattr(super(cls, cls), method):
                    return cls.foo == super(cls).foo
                return False

            valid_classes = list(type(self).__bases__)
            valid_classes.append(type(self))
            try:
                for base in valid_classes:
                    if "config_updated" in vars(base):  # base's own override
                        base.config_updated(self, self._config)
            except Exception:
                vars(self).update(old_state)
                self.logsec.diag = old_diag
                raise

            _LOGGER.debug("Effect %s config updated to %s.", self.NAME, self._config)

            if self._virtual:
                self._ledfx.events.fire_event(
                    EffectUpdatedEvent(self.id, self._virtual.id)
                )

    def config_updated(self, config):
        """Optional event for when an effect's config is updated."""

    def _render(self):
        with self.lock:
            if self._active:
                self.log_sec()
                self.render()
                self.try_log()

    def render(self):
        """To be implemented by child effect Must act on self.pixels, setting the
        values of it The effect can use self.pixels to see the previous effect
        frame if it wants to use it for something
        """

    def get_pixels(self):
        """Get the current pixels for the effect and apply flip, mirror, blur,
        brightness and background color transformations
        """
        with self.lock:
            pixels = None
            if hasattr(self, "pixels"):
                if self.pixels is not None:
                    pixels = np.copy(self.pixels)
                    config = self.config

                    if self.flip:
                        pixels = np.flipud(pixels)

                    if self.mirror:
                        mirrored_pixels = np.concatenate((pixels[::-1], pixels))
                        pixels = np.maximum(mirrored_pixels[::2], mirrored_pixels[1::2])

                    if self.bg_color_use and self.background_mode == "additive":
                        pixels += self._bg_color

                    if self.brightness is not None:
                        np.multiply(
                            pixels,
                            self.brightness,
                            out=pixels,
                            casting="unsafe",
                        )

                    if config.blur != 0.0 and self.pixel_count > 3:
                        kernel = _gaussian_kernel1d(config.blur, 0, len(pixels))

                        pixels[:, 0] = np.convolve(
                            pixels[:, 0], kernel, mode="same"
                        )  # R
                        pixels[:, 1] = np.convolve(
                            pixels[:, 1], kernel, mode="same"
                        )  # G
                        pixels[:, 2] = np.convolve(
                            pixels[:, 2], kernel, mode="same"
                        )  # B
                return pixels

    @property
    def is_active(self):
        """Return if the effect is currently active"""
        return self._active

    @property
    def pixel_count(self):
        """Returns the number of pixels for the channel"""
        return len(self.pixels)

    @property
    def name(self):
        return self.NAME

    def log_sec(self):
        self.now = timeit.default_timer()
        self.passed = self.now - self._last_frame_time
        self._last_frame_time = self.now
        self.logsec.log_sec(self.now)

    def try_log(self):
        return self.logsec.try_log()


class Effects(RegistryLoader):
    """Thin wrapper around the effect registry that manages effects"""

    PACKAGE_NAME = "ledfx.effects"

    def __init__(self, ledfx):
        super().__init__(ledfx=ledfx, cls=Effect, package=self.PACKAGE_NAME)
        self._ledfx.audio = None
