from abc import ABC, abstractmethod

from ledfx.nowplaying.models import TrackMetadata


class AlbumArtProvider(ABC):
    @abstractmethod
    async def resolve(self, metadata: TrackMetadata) -> bytes | None:
        """Return image bytes, or None for missing artwork and network failures."""
        ...
