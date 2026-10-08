"""API endpoints for image cache management."""

import logging

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.utils import get_image_cache

_LOGGER = logging.getLogger(__name__)


class CacheImagesEndpoint(RestEndpoint):
    """REST API endpoint for image cache statistics and management."""

    ENDPOINT_PATH = "/api/cache/images"

    async def get(self) -> web.Response:
        """Get cache statistics and entries."""
        cache = get_image_cache()

        if not cache:
            return await self.invalid_request(
                message="Image cache not initialized",
                type="error",
            )

        stats = cache.get_stats()
        stats["cache_policy"] = {
            "expiration": "none",
            "refresh": "explicit only",
            "eviction": "LRU when limits exceeded",
        }

        return await self.bare_request_success(stats)

    async def delete(self, request: web.Request) -> web.Response:
        """Clear cache for specific URL or entire cache."""
        cache = get_image_cache()

        if not cache:
            return await self.invalid_request(
                message="Image cache not initialized",
                type="error",
            )

        url = request.query.get("url")
        all_variants = request.query.get("all_variants", "false").lower() == "true"

        if url:
            if all_variants:
                cleared_count = cache.delete_all_for_url(url)
                return await self.bare_request_success({"cleared_count": cleared_count})
            else:
                deleted = cache.delete(url)
                return await self.bare_request_success(
                    {"deleted": deleted, "cleared_count": 1 if deleted else 0}
                )
        else:
            result = cache.clear()
            return await self.bare_request_success(result)
