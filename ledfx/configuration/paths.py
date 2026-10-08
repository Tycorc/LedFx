"""Config directory and file locations, logging setup and core constants."""

import datetime
import logging
import os
import sys

_LOGGER = logging.getLogger(__name__)

CONFIG_DIRECTORY = ".ledfx"

PRIVATE_KEY_FILE = "privkey.pem"
CHAIN_KEY_FILE = "fullchain.pem"

_default_wled_settings = {
    "wled_preferred_mode": "UDP",
    "realtime_gamma_enabled": False,
    "force_max_brightness": False,
    "realtime_dmx_mode": "MultiRGB",
    "start_universe_setting": 1,
    "dmx_address_start": 1,
    "inactivity_timeout": 1,
}

VISUALISATION_CONFIG_KEYS = [
    "visualisation_fps",
    "visualisation_maxlen",
]


class Transmission:
    BASE64_COMPRESSED = "compressed"
    UNCOMPRESSED = "uncompressed"


def load_logger():
    global _LOGGER
    _LOGGER = logging.getLogger(__name__)


def get_default_config_directory() -> str:
    """Get the default configuration directory."""

    base_dir = os.getenv("APPDATA") if os.name == "nt" else os.path.expanduser("~")
    return os.path.join(base_dir, CONFIG_DIRECTORY)


def get_profile_dump_location(config_dir: str) -> str:
    """Returns the location for dumping the profile."""
    date_time = datetime.datetime.now().astimezone().strftime("%d-%m-%y_%H-%M-%S")
    return os.path.join(config_dir, f"LedFx_{date_time}.profile")


def get_log_file_location(config_dir: str) -> str:
    """Returns the absolute file path of the log file."""
    log_file_path = os.path.abspath(os.path.join(config_dir, "ledfx.log"))
    return log_file_path


def get_ssl_certs(config_dir: str) -> tuple[str, str] | None:
    """Return (fullchain, private_key) paths, or None unless both files exist."""
    ssl_dir = os.path.join(config_dir, "ssl")

    if not os.path.exists(ssl_dir):
        return None

    key_path = os.path.join(ssl_dir, PRIVATE_KEY_FILE)
    chain_path = os.path.join(ssl_dir, CHAIN_KEY_FILE)

    if os.path.isfile(key_path) and os.path.isfile(chain_path):
        return (chain_path, key_path)
    return None


def ensure_config_directory(config_dir: str) -> None:
    """Validate that the config directory is valid."""
    if not os.path.isdir(config_dir):
        try:
            os.mkdir(config_dir)
        except OSError:
            _LOGGER.critical(
                "Unable to create configuration directory at %s. Shutting down.",
                config_dir,
            )
            sys.exit(1)
