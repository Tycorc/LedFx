import asyncio
import logging
from json import JSONDecodeError

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.utils import get_image_cache, open_image

_LOGGER = logging.getLogger(__name__)


class CacheRefreshEndpoint(RestEndpoint):
    """REST API endpoint for explicit cache refresh."""

    ENDPOINT_PATH = "/api/cache/images/refresh"

    async def post(self, request: web.Request) -> web.Response:
        """Refresh a remote image, or clear local/all-variant cache entries."""
        cache = get_image_cache()

        if not cache:
            return await self.invalid_request(
                message="Image cache not initialized",
                type="error",
            )

        try:
            data = await request.json()
        except JSONDecodeError:
            return await self.json_decode_error()

        url = data.get("url")
        if not url:
            return await self.invalid_request(
                message="Missing 'url' in request body",
                type="error",
            )

        all_variants = data.get("all_variants", False)
        if not isinstance(all_variants, bool):
            return await self.invalid_request(
                message="Invalid 'all_variants' parameter. Must be a boolean (true or false).",
                type="error",
            )

        if all_variants:
            cleared_count = cache.delete_all_for_url(url)
            return await self.bare_request_success({"cleared_count": cleared_count})

        if url.startswith(("http://", "https://")):
            deleted = cache.delete(url)

            _LOGGER.info("Actively refreshing cached URL: %s", url)
            image = await asyncio.to_thread(
                open_image, url, force_refresh=True, config_dir=self._ledfx.config_dir
            )

            if image:
                return await self.bare_request_success({"refreshed": True})
            else:
                return await self.invalid_request(
                    message=f"Failed to refresh URL: {url}. Image could not be downloaded.",
                    type="error",
                )
        else:
            deleted = cache.delete(url)
            return await self.bare_request_success({"refreshed": deleted})
