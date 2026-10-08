"""Sendspin configuration schema and constants."""

import logging
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ledfx.configuration.models import LedFxConfig
    from ledfx.effects.audio import AudioAnalysisSource

_LOGGER = logging.getLogger(__name__)

DEFAULT_SERVER_URL = "ws://192.168.1.12:8927/sendspin"
DEFAULT_CLIENT_NAME = "LedFx"

PRODUCT_NAME = "LedFx"
MANUFACTURER = "LedFx Developers"

BUFFER_CAPACITY = 384000


class _LedFx(Protocol):
    """Core state needed by Sendspin's always-on startup helper."""

    @property
    def config(self) -> "LedFxConfig": ...

    audio: "AudioAnalysisSource | None"


def validate_sendspin_server_url(url: object) -> tuple[bool, str]:
    """Return (valid, reason) for an already-stripped ws/wss server URL."""
    if not isinstance(url, str):
        return False, "server_url must be a string"

    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname
        port = parsed.port
    except Exception:  # noqa: BLE001
        return False, "server_url could not be parsed"

    if parsed.scheme not in ("ws", "wss"):
        return (
            False,
            f"server_url scheme '{parsed.scheme}' is not allowed; must be ws or wss",
        )

    if not hostname:
        return False, "server_url must contain a non-empty hostname"

    if port is not None and not (0 <= port <= 65535):
        return (
            False,
            f"server_url port {port} is out of range (0-65535)",
        )

    path = parsed.path
    if "\x00" in path:
        return False, "server_url path contains null bytes"
    if ".." in path.split("/"):
        return False, "server_url path contains path-traversal sequence"

    return True, ""


def is_always_on(
    device_idx: object,
    query_devices: Callable[[], Sequence[Mapping[str, object]]],
    query_hostapis: Callable[[], Sequence[Mapping[str, object]]],
) -> bool:
    """Check if the audio device at device_idx is a Sendspin device."""
    if not isinstance(device_idx, int) or device_idx < 0:
        return False
    try:
        devices = query_devices()
        hostapis = query_hostapis()
        if device_idx >= len(devices):
            return False
        hostapi_index = devices[device_idx].get("hostapi")
        if not isinstance(hostapi_index, int) or not 0 <= hostapi_index < len(hostapis):
            return False
        hostapi_name = hostapis[hostapi_index].get("name")
        return hostapi_name == "SENDSPIN"
    except Exception as exc:  # noqa: BLE001
        _LOGGER.debug(
            "is_always_on: exception checking device %s: %s",
            device_idx,
            exc,
        )
        return False


def eager_start(ledfx: _LedFx) -> None:
    """Start always-on Sendspin audio after servers load, without waiting for an
    effect.
    """
    config = ledfx.config
    if not config.sendspin_always_on:
        return

    audio_config = config.audio.model_dump()
    device_idx = config.audio.audio_device
    device_name = config.audio.audio_device_name

    _LOGGER.debug(
        "eager_start: audio_device=%s audio_device_name=%r sendspin_always_on=%s",
        device_idx,
        device_name,
        config.sendspin_always_on,
    )

    from ledfx.effects.audio import AudioAnalysisSource, AudioInputSource

    name_is_sendspin = device_name.startswith("SENDSPIN:")
    idx_is_sendspin = is_always_on(
        device_idx,
        AudioInputSource.query_devices,
        AudioInputSource.query_hostapis,
    )
    _LOGGER.debug(
        "eager_start: name_is_sendspin=%s idx_is_sendspin=%s",
        name_is_sendspin,
        idx_is_sendspin,
    )

    if not (name_is_sendspin or idx_is_sendspin):
        return

    _LOGGER.info(
        "Sendspin always-on: eagerly starting audio (device %s, name=%r)",
        device_idx,
        device_name,
    )

    existing_audio = ledfx.audio
    if existing_audio is not None:
        existing_audio.update_config(audio_config)
        return

    ledfx.audio = AudioAnalysisSource(ledfx, audio_config)
