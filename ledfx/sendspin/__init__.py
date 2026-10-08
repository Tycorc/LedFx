"""Optional Sendspin audio; unavailable before Python 3.12 or when imports fail."""

import logging
import sys

_LOGGER = logging.getLogger(__name__)
__all__: list[str] = []

if sys.version_info >= (3, 12):
    try:
        from ledfx.sendspin.stream import SendspinAudioStream

        __all__ = ["SendspinAudioStream"]
        SENDSPIN_AVAILABLE = True
    except (ImportError, OSError) as _exc:
        SENDSPIN_AVAILABLE = False
        _LOGGER.warning(
            "Sendspin import failed: %s",
            _exc,
            exc_info=_exc,
        )
else:
    SENDSPIN_AVAILABLE = False
