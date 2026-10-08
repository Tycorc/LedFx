import time
from functools import lru_cache

import numpy as np
from numpy import asarray, extract, mod, nan, pi, place, zeros


@lru_cache(maxsize=64)
def _normalized_linspace(size):
    return np.linspace(0, 1, size)


def interpolate_pixels(pixels, new_length):
    if len(pixels) == new_length:
        return pixels

    x_old = _normalized_linspace(len(pixels))
    x_new = _normalized_linspace(new_length)
    new_pixels = np.zeros((len(x_new), pixels.shape[1]))

    new_pixels[:, 0] = np.interp(x_new, x_old, pixels[:, 0])  # R
    new_pixels[:, 1] = np.interp(x_new, x_old, pixels[:, 1])  # G
    new_pixels[:, 2] = np.interp(x_new, x_old, pixels[:, 2])  # B
    return new_pixels


# Copied from scipy to avoid importing the entire dependency.
# https://github.com/scipy/scipy/blob/main/scipy/signal/_waveforms.py
# Copyright (c) 2001-2002 Enthought, Inc. 2003-2022, SciPy Developers.
# All rights reserved.

# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:

# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.

# 2. Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.

# 3. Neither the name of the copyright holder nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.


# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
def sawtooth(t, width=1):
    """Return a non-band-limited 2*pi-periodic waveform; width 0..1 sets the rising
    ramp.
    """
    t, w = asarray(t), asarray(width)
    w = asarray(w + (t - t))
    t = asarray(t + (w - w))
    if t.dtype.char in ["fFdD"]:
        ytype = t.dtype.char
    else:
        ytype = "d"
    y = zeros(t.shape, ytype)

    mask1 = (w > 1) | (w < 0)
    place(y, mask1, nan)

    tmod = mod(t, 2 * pi)

    mask2 = (1 - mask1) & (tmod < w * 2 * pi)
    tsub = extract(mask2, tmod)
    wsub = extract(mask2, w)
    place(y, mask2, tsub / (pi * wsub) - 1)

    mask3 = (1 - mask1) & (1 - mask2)
    tsub = extract(mask3, tmod)
    wsub = extract(mask3, w)
    place(y, mask3, (pi * (wsub + 1) - tsub) / (pi * (1 - wsub)))
    return y


# End BSD-3 Licensed Code


def triangle(a):
    phase = np.asarray(a * np.pi * 2)
    if phase.dtype in (np.dtype("float16"), np.dtype("float32"), np.dtype("float64")):
        # sawtooth's float64 width promotes the already-scaled phase. Keep
        # that rounding order, but avoid extracting and scattering both halves.
        phase = np.remainder(phase.astype(np.float64, copy=False), 2 * np.pi)
        a = np.where(
            phase < np.pi,
            phase / (np.pi * 0.5) - 1,
            (np.pi * 1.5 - phase) / (np.pi * 0.5),
        )
    else:
        a = sawtooth(phase, 0.5)
    np.multiply(a, 0.5, out=a)
    return np.add(a, 0.5)


class ExpFilter:
    def __init__(self, val=None, alpha_decay=0.5, alpha_rise=0.5):
        assert 0.0 < alpha_decay < 1.0, "Invalid decay smoothing factor"
        assert 0.0 < alpha_rise < 1.0, "Invalid rise smoothing factor"
        self.alpha_decay = alpha_decay
        self.alpha_rise = alpha_rise
        self.value = val

    def update(self, value):
        if self.value is None:
            self.value = value
            return self.value

        if isinstance(self.value, (list, np.ndarray, tuple)):
            alpha = value - self.value
            alpha[alpha > 0.0] = self.alpha_rise
            alpha[alpha <= 0.0] = self.alpha_decay
        else:
            alpha = self.alpha_rise if value > self.value else self.alpha_decay

        self.value = alpha * value + (1.0 - alpha) * self.value

        return self.value


class CalibratorPatternCache:
    _CALIBRATION_COLORS = None
    _BLACK_COLOR = None
    _WHITE_COLOR = None

    def __init__(self, animation_period=3.0, dim_factor=0.2):
        self.animation_period = animation_period
        self.dim_factor = dim_factor
        self._time_offset = time.perf_counter()  # For animation timing
        self._color_index = 0  # For cycling through colors

        if CalibratorPatternCache._CALIBRATION_COLORS is None:
            from ledfx.color import parse_color

            color_names = [
                "red",
                "green",
                "blue",
                "cyan",
                "magenta",
                "#ffff00",
            ]
            CalibratorPatternCache._CALIBRATION_COLORS = [
                np.array(parse_color(name), dtype=float) for name in color_names
            ]
            CalibratorPatternCache._BLACK_COLOR = np.array([0.0, 0.0, 0.0], dtype=float)
            CalibratorPatternCache._WHITE_COLOR = np.array(
                parse_color("white"), dtype=float
            )

    def get_next_color(self):
        color = self._CALIBRATION_COLORS[self._color_index]
        self._color_index = (self._color_index + 1) % len(self._CALIBRATION_COLORS)
        return color

    def reset_color_sequence(self):
        self._color_index = 0

    @property
    def black_color(self):
        return self._BLACK_COLOR

    @property
    def white_color(self):
        return self._WHITE_COLOR

    @staticmethod
    @lru_cache(maxsize=32)
    def _create_base_pattern(length, dim_factor):
        indices = np.arange(length)

        phase = (indices / length) * 4.0  # 0-4 range

        brightness = np.ones(length)

        mask_phase1 = (phase >= 1.0) & (phase < 2.0)
        mask_phase2 = (phase >= 2.0) & (phase < 3.0)
        mask_phase3 = (phase >= 3.0) & (phase < 4.0)

        brightness[mask_phase1] = 1.0 - (phase[mask_phase1] - 1.0) * (1.0 - dim_factor)
        brightness[mask_phase2] = dim_factor
        brightness[mask_phase3] = dim_factor + (phase[mask_phase3] - 3.0) * (
            1.0 - dim_factor
        )

        return brightness[:, np.newaxis]

    def get_pattern(self, color, length, step):
        base_pattern = self._create_base_pattern(length, self.dim_factor)

        pattern = base_pattern * color

        time_fraction = (
            (time.perf_counter() - self._time_offset) % self.animation_period
        ) / self.animation_period
        shift_amount = int(length * time_fraction * step)

        if shift_amount != 0:
            pattern = np.roll(pattern, shift_amount, axis=0)

        return pattern

    def get_pattern_batch(self, segments_data, current_time=None):
        if current_time is None:
            current_time = time.perf_counter()

        time_fraction = (
            (current_time - self._time_offset) % self.animation_period
        ) / self.animation_period

        patterns = []
        for color, length, step in segments_data:
            base_pattern = self._create_base_pattern(length, self.dim_factor)
            pattern = base_pattern * color

            shift_amount = int(length * time_fraction * step)
            if shift_amount != 0:
                pattern = np.roll(pattern, shift_amount, axis=0)

            patterns.append(pattern)

        return patterns
