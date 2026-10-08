import time

import numpy as np
from numpy.typing import NDArray
from pydantic import Field

from ledfx.configuration.plugin import TypedConfig
from ledfx.effects import Effect
from ledfx.effects.gradient import GradientEffect


@Effect.no_registration
class HSVEffect(GradientEffect):
    class Config(GradientEffect.Config):
        fix_hues: bool = Field(
            True, description="Use perceptually even hue distribution"
        )

    config = TypedConfig(Config)

    _start_time = time.time_ns()
    _conversion_factor = 65.536 * 1e9
    _hsv_roll_counter = 0

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        self._dt = 0
        self.hsv_array = None
        self._h_indices: NDArray[np.intp] = np.empty(0, dtype=int)
        self._pixel_max: NDArray[np.float64] = np.empty((0, 1))
        self._saturation_work: NDArray[np.float64] = np.empty(0)
        self._inverse_saturation: NDArray[np.float64] = np.empty(0)

    def on_activate(self, pixel_count):
        self.hsv_array = np.zeros((pixel_count, 3))
        self._h_indices = np.zeros(pixel_count, dtype=int)
        self._pixel_max = np.zeros((pixel_count, 1))
        self._saturation_work = np.empty(pixel_count)
        self._inverse_saturation = np.empty(pixel_count)

    def config_updated(self, config):
        self._gradient_curve = None

    def render(self):
        self._dt = time.time_ns() - self._start_time
        self.render_hsv()

        h = self.hsv_array[:, 0]
        s = self.hsv_array[:, 1]
        v = self.hsv_array[:, 2]

        if self.config.fix_hues:
            self.fix_hue_fast(h)

        pixels = self.pixels
        assert pixels is not None

        np.mod(h, 1, out=h)
        np.multiply(h, self.pixel_count - 1, out=h)
        np.floor(h, out=h)
        self._h_indices[:] = h.astype(int, copy=False)

        gradient = self.get_gradient()
        assert gradient is not None
        np.take(gradient.T, self._h_indices, axis=0, out=pixels)

        # Three explicit channels avoid the costly short-axis reduction and
        # full RGB temporaries. Keep the arithmetic order unchanged so the
        # saturation/value conversion preserves floating-point RGB output.
        maximum = self._pixel_max[:, 0]
        np.maximum(pixels[:, 0], pixels[:, 1], out=maximum)
        np.maximum(maximum, pixels[:, 2], out=maximum)
        np.subtract(1, s, out=self._inverse_saturation)
        for channel in range(3):
            column = pixels[:, channel]
            np.subtract(maximum, column, out=self._saturation_work)
            np.multiply(
                self._saturation_work,
                self._inverse_saturation,
                out=self._saturation_work,
            )
            np.add(column, self._saturation_work, out=column)
            np.multiply(column, v, out=column)

        self.roll_gradient()

    def render_hsv(self):
        """Subclasses must update self.hsv_array."""

    def time(self, modifier=1.0, timestep=None):
        """Return a 0..1 sawtooth with period 65.536 / modifier seconds."""
        period = self._conversion_factor / modifier
        if timestep is None:
            timestep = self._dt
        return (timestep % period) / period

    def triangle(self, x=1.0):
        """Convert a wrapped 0..1 sawtooth to a 0..1 triangle."""
        return 1 - 2 * np.abs(x - 0.5)

    def sin(self, x=1.0):
        """Convert a wrapped 0..1 sawtooth to a 0..1 sinusoid."""
        return 0.5 * np.sin(x * 2 * np.pi) + 0.5

    def square(self, x=1.0, duty=0.5):
        """Convert a wrapped 0..1 sawtooth to a square wave with the given duty
        cycle.
        """
        return 0.5 * np.sign(duty - x) + 0.5

    def array_triangle(self, a):
        """Perform the 'triangle' wavefunction on an array"""
        np.subtract(a, 0.5, out=a)
        np.abs(a, out=a)
        np.multiply(a, 2, out=a)
        np.subtract(1, a, out=a)

    def array_sin(self, a):
        """Perform the 'sin' wavefunction on an array"""
        np.multiply(2 * np.pi, a, out=a)
        np.sin(a, out=a)
        np.multiply(0.5, a, out=a)
        np.add(0.5, a, out=a)

    def array_square(self, a, duty=0.5):
        """Perform the 'square' wavefunction on an array"""
        np.subtract(duty, a, out=a)
        np.sign(a, out=a)
        np.multiply(0.5, a, out=a)
        np.add(0.5, a, out=a)

    def fix_hue_fast(self, hue):
        """Map perceptual hue to 0..1 HSV hue; see docs/README.md for the tradeoff."""
        np.mod(hue, 1, out=hue)
        np.subtract(hue, 0.5, out=hue)
        np.divide(hue, 2, out=hue)
        self.array_sin(hue)
        return hue
