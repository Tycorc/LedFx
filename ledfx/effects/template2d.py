import logging

from pydantic import Field

from ledfx.configuration.plugin import TypedConfig
from ledfx.effects import Effect
from ledfx.effects.twod import Twod

_LOGGER = logging.getLogger(__name__)


@Effect.no_registration
class Template2d(Twod):
    NAME = "Template2d"
    CATEGORY = "Matrix"
    HIDDEN_KEYS = Twod.HIDDEN_KEYS + []
    ADVANCED_KEYS = Twod.ADVANCED_KEYS + []

    class Config(Twod.Config):
        a_switch: bool = Field(False, description="Does a boolean thing")

    config = TypedConfig(Config)

    def __init__(self, ledfx, config):
        # set any default values first, as config_updated will be called
        # from the super().__init__() which may depend on them
        self.bar = 0
        super().__init__(ledfx, config)

    def config_updated(self, config):
        super().config_updated(config)
        # copy over your configs here into variables
        self.a_switch = self.config.a_switch

    def do_once(self):
        super().do_once()

    def audio_data_updated(self, data):
        # Grab your audio input here, such as bar oscillator
        self.bar = data.bar_oscillator()

    def draw(self):

        # look in this function for basic lines etc, use pillow primitives
        # for regular shapes
        if self.test:
            self.draw_test(self.m_draw)
