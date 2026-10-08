"""Forward Sendspin metadata, retaining omitted fields and clearing explicit None."""

import logging
from typing import TYPE_CHECKING, Protocol

from ledfx.nowplaying.models import TrackMetadata

if TYPE_CHECKING:
    from ledfx.nowplaying.service import NowPlayingService

_LOGGER = logging.getLogger(__name__)

SOURCE_ID = "sendspin"


class LedFxNowPlaying(Protocol):
    @property
    def now_playing(self) -> "NowPlayingService | None": ...


class _ServerState(Protocol):
    """Metadata field consumed from a Sendspin server state update."""

    @property
    def metadata(self) -> object: ...


class SendspinNowPlayingProvider:
    """Accumulate incremental Sendspin metadata for the Now Playing service."""

    def __init__(self, ledfx: LedFxNowPlaying) -> None:
        self._ledfx = ledfx
        self._last_artwork_url: str | None = None
        self._title: str | None = None
        self._artist: str | None = None
        self._album: str | None = None
        self._artwork_url: str | None = None
        _LOGGER.info("Sendspin Now Playing provider initialized")

    def on_metadata(self, server_state_payload: _ServerState) -> None:
        """Keep UndefinedField values, clear None values, and apply explicit updates."""
        from aiosendspin.models.metadata import SessionUpdateMetadata
        from aiosendspin.models.types import UndefinedField

        metadata = server_state_payload.metadata
        if metadata is None:
            return

        if not isinstance(metadata, SessionUpdateMetadata):
            _LOGGER.debug("Ignoring non-metadata server state update")
            return

        if not isinstance(metadata.title, UndefinedField):
            self._title = metadata.title
        if not isinstance(metadata.artist, UndefinedField):
            self._artist = metadata.artist
        if not isinstance(metadata.album, UndefinedField):
            self._album = metadata.album
        if not isinstance(metadata.artwork_url, UndefinedField):
            self._artwork_url = metadata.artwork_url

        track_metadata = TrackMetadata(
            source_id=SOURCE_ID,
            title=self._title,
            artist=self._artist,
            album=self._album,
            artwork_url=self._artwork_url,
        )

        now_playing = getattr(self._ledfx, "now_playing", None)
        if now_playing is None:
            return
        now_playing.set_metadata(SOURCE_ID, track_metadata)

        if (
            self._artwork_url is not None
            and self._artwork_url != self._last_artwork_url
        ):
            self._last_artwork_url = self._artwork_url
            now_playing.set_artwork_url(SOURCE_ID, self._artwork_url)
        elif self._artwork_url is None and self._last_artwork_url is not None:
            self._last_artwork_url = None
            now_playing.clear_artwork(SOURCE_ID)

    def clear(self) -> None:
        """Clear Now Playing state and reset accumulated state."""
        now_playing = getattr(self._ledfx, "now_playing", None)
        if now_playing is not None:
            now_playing.clear(SOURCE_ID)
        self._last_artwork_url = None
        self._title = None
        self._artist = None
        self._album = None
        self._artwork_url = None
        _LOGGER.info("Sendspin Now Playing provider cleared")
