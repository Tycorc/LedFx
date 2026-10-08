import itertools
import logging
import timeit
from typing import Annotated

import numpy as np
from PIL import Image, ImageDraw
from pydantic import Field

from ledfx.configuration.fields import CoercedFloat, CoercedInt, OneOf
from ledfx.configuration.plugin import TypedConfig
from ledfx.effects.audio import AudioReactiveEffect
from ledfx.effects.gradient import GradientEffect
from ledfx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)

RENDER_MAPPINGS = {
    "Points": "points_render",
    "Lines": "lines_render",
    "Fill": "fill_render",
}


class Bleeper:
    """Render a rolling amplitude history as points, lines, or filled masks."""

    def __init__(self):
        """Initialise the bleeper with a single amplitude value so that further init
        cycles can copy forward
        """
        self.amplitudes = np.zeros(1)

    def init(
        self,
        shape,
        scroll_time,
        points,
        points_linear,
        mirror,
        render_func,
        size,
    ):
        """Reconfigure the mask without losing the current amplitude history."""
        self.points = points
        self.points_linear = points_linear
        self.coords = np.zeros((self.points, 2))
        self.coords[:, 0] = self.points_linear
        self.coords[:, 1] = 0.5

        old_amplitudes = self.amplitudes.copy()
        self.amplitudes = np.zeros(self.points)
        length = min(len(self.amplitudes), len(old_amplitudes))
        self.amplitudes[:length] = old_amplitudes[:length]

        self.shape = shape
        self.norm_shape = (self.shape[0] - 1, self.shape[1] - 1)
        self.scroll_time = scroll_time
        self.last_time = timeit.default_timer()
        self.progress = 0.0
        self.step_time = self.scroll_time / self.points
        self.mirror = mirror
        self.render_func = render_func
        self.size = size

    def update(self, power):
        """time invariant handling of the rolling points and update with latest power
        value
        """
        now = timeit.default_timer()
        delta_t = now - self.last_time
        self.progress = self.progress + delta_t
        while self.progress > self.step_time:
            self.progress = self.progress - self.step_time
            self.amplitudes = np.roll(self.amplitudes, 1)
            self.amplitudes[0] = power
        self.last_time = now

    def render(self, m_draw):
        """Prepare mask image Set up common render lists, account for mirror Call the
        currently active render_func
        """
        mask_image = Image.new("L", self.shape, 0)
        mask_draw = ImageDraw.Draw(mask_image)

        list_plot_coords_top = None
        list_plot_coords_bot = None

        plot_coords_top = self.coords.copy()
        if self.mirror:
            plot_coords_bot = plot_coords_top.copy()
            plot_coords_top[:, 1] += self.amplitudes / 2
            plot_coords_bot[:, 1] -= self.amplitudes / 2

            plot_coords_top = np.clip(plot_coords_top, 0, 1)
            plot_coords_bot = np.clip(plot_coords_bot, 0, 1)
            plot_coords_top = np.round(plot_coords_top * self.norm_shape).astype(int)
            plot_coords_bot = np.round(plot_coords_bot * self.norm_shape).astype(int)
            list_plot_coords_top = [tuple(c) for c in plot_coords_top]
            list_plot_coords_bot = [tuple(c) for c in plot_coords_bot]
        else:
            plot_coords_top[:, 1] += -0.5 + self.amplitudes
            plot_coords_top = np.clip(plot_coords_top, 0, 1)
            plot_coords_top = np.round(plot_coords_top * self.norm_shape).astype(int)
            list_plot_coords_top = [tuple(c) for c in plot_coords_top]

        getattr(self, self.render_func)(
            mask_draw, list_plot_coords_top, list_plot_coords_bot
        )
        return mask_image

    def points_render(self, m_draw, list_plot_coords_top, list_plot_coords_bot):
        """Points style render of the bleep effect"""
        if self.mirror:
            for xy in list_plot_coords_top:
                m_draw.point(xy, fill=255)
            for xy in list_plot_coords_bot:
                m_draw.point(xy, fill=255)
        else:
            for xy in list_plot_coords_top:
                m_draw.point(xy, fill=255)

    def lines_render(self, m_draw, list_plot_coords_top, list_plot_coords_bot):
        """Lines style render of the bleep effect"""
        if self.mirror:
            for start, end in itertools.pairwise(list_plot_coords_top):
                m_draw.line([start, end], fill=255, width=self.size)
            for start, end in itertools.pairwise(list_plot_coords_bot):
                m_draw.line([start, end], fill=255, width=self.size)
        else:
            for start, end in zip(
                [tuple(c) for c in list_plot_coords_top],
                [tuple(c) for c in list_plot_coords_top[1:]],
            ):
                m_draw.line([start, end], fill=255, width=self.size)

    def fill_render(self, m_draw, list_plot_coords_top, list_plot_coords_bot):
        """Filled Polygon style render of the bleep effect"""
        if self.mirror:
            for (x0, y0), (x1, y1), (x2, y2), (x3, y3) in zip(
                list_plot_coords_top,
                list_plot_coords_bot,
                list_plot_coords_bot[1:],
                list_plot_coords_top[1:],
            ):
                m_draw.polygon([(x0, y0), (x1, y1), (x2, y2), (x3, y3)], fill=255)
        else:
            for (x0, y0), (x1, y1) in itertools.pairwise(list_plot_coords_top):
                m_draw.polygon([(x0, 0), (x1, 0), (x1, y1), (x0, y0)], fill=255)


class Bleep(Twod, GradientEffect):
    NAME = "Bleep"
    CATEGORY = "Matrix"
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + ["gradient_roll"]
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + []

    class Config(Twod.Config, GradientEffect.Config):
        mirror_effect: bool = Field(False, description="mirror effect")
        grad_power: bool = Field(
            False, description="Use gradient in power dimension instead of time"
        )
        scroll_time: CoercedFloat = Field(
            1.0, description="Time to scroll the bleep", ge=0.1, le=5.0
        )
        frequency_range: Annotated[
            str, OneOf(list(AudioReactiveEffect.POWER_FUNCS_MAPPING.keys()))
        ] = Field(
            "Lows (beat+bass)", description="Frequency range for the beat detection"
        )
        draw: Annotated[str, OneOf(list(RENDER_MAPPINGS.keys()))] = Field(
            "Lines", description="How to plot the data"
        )
        points: CoercedInt = Field(
            64, description="How many historical points to capture", ge=2, le=64
        )
        size: CoercedInt = Field(1, description="Line width only", ge=1, le=8)

    config = TypedConfig(Config)

    def __init__(self, ledfx, config):
        super().__init__(ledfx, config)
        self.bleeper = Bleeper()

    def config_updated(self, config):
        super().config_updated(config)
        self.points = self.config.points
        self.mirror_effect = self.config.mirror_effect
        self.grad_power = self.config.grad_power
        self.scroll_time = self.config.scroll_time
        self.power_func = self.POWER_FUNCS_MAPPING[self.config.frequency_range]
        self.render_func = RENDER_MAPPINGS[self.config.draw]
        self.size = self.config.size

    def do_once(self):
        """Initialize layout after r_width/r_height are available; config_updated is
        too early.
        """
        super().do_once()
        self.points_linear = np.linspace(0, 1, self.points)

        lin_horizontal = np.linspace(0, 1, self.r_width)
        if self.mirror_effect:
            if self.r_height % 2 == 0:
                half_height = np.linspace(1, 0, self.r_height // 2)
                lin_mirrored = np.concatenate((half_height, half_height[::-1]))
            else:
                half_height = np.linspace(1, 0, (self.r_height // 2) + 1)
                lin_mirrored = np.concatenate((half_height, half_height[::-1][1:]))
            lin_vertical = lin_mirrored
        else:
            lin_vertical = np.linspace(0, 1, self.r_height)

        self.bleeper.init(
            (self.r_width, self.r_height),
            self.scroll_time,
            self.points,
            self.points_linear,
            self.mirror_effect,
            self.render_func,
            self.size,
        )

        self.gradient_image = Image.new("RGB", (self.r_width, self.r_height))
        self.gradient_draw = ImageDraw.Draw(self.gradient_image)
        if self.grad_power:
            colors = self.get_gradient_color_vectorized1d(lin_vertical).astype(int)
            for y in range(self.r_height):
                self.gradient_draw.line(
                    [(0, y), (self.r_width - 1, y)],
                    fill=tuple(colors[y]),
                    width=1,
                )
        else:
            colors = self.get_gradient_color_vectorized1d(lin_horizontal).astype(int)
            for x in range(self.r_width):
                self.gradient_draw.line(
                    [(x, 0), (x, self.r_height - 1)],
                    fill=tuple(colors[x]),
                    width=1,
                )

    def audio_data_updated(self, data):
        if not self.init:
            self.bleeper.update(getattr(data, self.power_func)())

    def draw(self):

        if self.test:
            self.draw_test(self.m_draw)

        mask = self.bleeper.render(self.m_draw)
        self.matrix = Image.composite(self.gradient_image, self.matrix, mask)
