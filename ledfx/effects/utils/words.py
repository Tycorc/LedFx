import logging
import math
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from ledfx.color import parse_color
from ledfx.consts import LEDFX_ASSETS_PATH
from ledfx.effects.utils.pose import Pose, biased_round

_LOGGER = logging.getLogger(__name__)

FONT_MAPPINGS = {
    "Roboto Regular": os.path.join(LEDFX_ASSETS_PATH, "fonts", "Roboto-Regular.ttf"),
    "Roboto Bold": os.path.join(LEDFX_ASSETS_PATH, "fonts", "Roboto-Bold.ttf"),
    "Roboto Black": os.path.join(LEDFX_ASSETS_PATH, "fonts", "Roboto-Black.ttf"),
    "Stop": os.path.join(LEDFX_ASSETS_PATH, "fonts", "Stop.ttf"),
    "Technique": os.path.join(LEDFX_ASSETS_PATH, "fonts", "technique.ttf"),
    "8bitOperatorPlus8": os.path.join(
        LEDFX_ASSETS_PATH, "fonts", "8bitOperatorPlus8-Regular.ttf"
    ),
    "Press Start 2P": os.path.join(LEDFX_ASSETS_PATH, "fonts", "PressStart2P.ttf"),
    "Blade-5x8": os.path.join(LEDFX_ASSETS_PATH, "fonts", "Blade-5x8.ttf"),
}


class Textblock:
    def __init__(self, text, font, disp_size, color="white"):
        """Create a new Textblock object"""
        self.text = text
        self.color = color
        self.ascent, self.descent = font.getmetrics()
        dummy_image = Image.new("L", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_image)
        left, top, right, bottom = dummy_draw.textbbox((0, 0), text, font=font)  # noqa: RUF059
        self.width = right - left
        self.height = self.descent + self.ascent
        self.w_width = self.width / (disp_size[0] / 2)
        self.w_height = self.height / (disp_size[0] / 2)
        self.h_width = self.width / (disp_size[1] / 2)
        self.h_height = self.height / (disp_size[1] / 2)

        self.image = Image.new("L", (self.width, self.height))  # , "grey")
        self.draw = ImageDraw.Draw(self.image)
        self.draw.text((0, 0), self.text, font=font, fill=color)
        self.pose = Pose(0, 0, 0, 1, 0, 1)

    def update(self, dt):
        """Advance the text block by dt seconds."""

        active = self.pose.update(dt)
        return active

    def calculate_final_size(self):
        """Return final (width, height) for off-screen clipping."""

        angle_rad = self.pose.ang * 2 * math.pi

        cos_angle = abs(math.cos(angle_rad))
        sin_angle = abs(math.sin(angle_rad))

        rotated_width = self.image.height * sin_angle + self.image.width * cos_angle
        rotated_height = self.image.height * cos_angle + self.image.width * sin_angle

        final_width = max(1, round(rotated_width * self.pose.size))
        final_height = max(1, round(rotated_height * self.pose.size))

        return final_width, final_height

    def render(self, target, resize_method, color=None, values=None, values2=None):
        """Render the Textblock object to the target image"""
        if self.pose.life > 0 and self.pose.alpha > 0.0 and self.pose.size > 0.0:
            pose_x = self.pose.x
            pose_y = self.pose.y
            c_width, c_height = self.calculate_final_size()
            half_width = target.width / 2
            half_height = target.height / 2
            e_x = round(abs(pose_x) * half_width) - c_width / 2
            e_y = round(abs(pose_y) * half_height) - c_height / 2
            if e_x < half_width and e_y < half_height:
                resized = self.image.rotate(
                    self.pose.ang * 360, expand=True, resample=resize_method
                )
                resized = resized.resize(
                    (
                        max(1, round(resized.width * self.pose.size)),
                        max(1, round(resized.height * self.pose.size)),
                    ),
                    resample=resize_method,
                )

                x = biased_round(((pose_x + 1) * half_width) - (resized.width / 2))
                y = biased_round(((pose_y + 1) * half_height) - (resized.height / 2))

                capped_alpha = min(1.0, max(0.0, self.pose.alpha))
                if capped_alpha < 1.0:
                    img_array = np.array(resized)
                    modified_array = np.clip(img_array * capped_alpha, 0, 255).astype(
                        np.uint8
                    )
                    resized = Image.fromarray(modified_array, mode="L")

                if color is not None:
                    color_img = Image.new("RGBA", resized.size, color)
                    r, g, b, a = color_img.split()  # noqa: RUF059
                    resized = Image.merge("RGBA", (r, g, b, resized))
                target.paste(resized, (x, y), resized)


class Sentence:
    def __init__(self, text, font_name, points, disp_size):
        """Create a new Sentence object"""
        self.text = text
        self.font_path = FONT_MAPPINGS[font_name]
        self.points = points
        self.start_color = parse_color("white")
        self.font = ImageFont.truetype(self.font_path, self.points)
        self.wordblocks = []

        for word in self.text.split():
            wordblock = Textblock(word, self.font, disp_size)
            self.wordblocks.append(wordblock)
            _LOGGER.debug("Wordblock %s created", word)
        self.space_block = Textblock(" ", self.font, disp_size)
        self.wordcount = len(self.wordblocks)
        self.color_points = np.array(
            [idx / max(1, self.wordcount - 1) for idx in range(self.wordcount)]
        )

        self.word_focus_active = False
        self.word_focus = -1
        self.word_focused_on = -1
        self.d_word_focus = 1
        self.word_focus_callback = None

    def update(self, dt):
        """Advance the sentence by dt seconds."""

        if self.word_focus_active:
            self.word_focus += self.d_word_focus * dt
            if self.word_focus >= 1.0:
                self.word_focused_on = (self.word_focused_on + 1) % self.wordcount
                self.word_focus %= 1.0

        for word in self.wordblocks:
            word.update(dt)

    def render(self, target, resize_method, color, values=None, values2=None):
        """Render the Sentence object to the target image"""
        color_len = len(color)

        for i, word in enumerate(self.wordblocks):
            if self.word_focus_active and i == self.word_focused_on:
                focus_color = tuple(color[i % color_len])
            else:
                word.render(
                    target,
                    resize_method,
                    tuple(color[i % color_len]),
                    values,
                    values2,
                )

        if self.word_focus_active:
            self.wordblocks[self.word_focused_on].render(
                target,
                resize_method,
                focus_color,
                values,
                values2,
            )
