import asyncio
import logging
import os

from aiohttp import web

from ledfx import assets
from ledfx.api import RestEndpoint
from ledfx.utils import get_image_cache, open_image

_LOGGER = logging.getLogger(__name__)


class AssetsDownloadEndpoint(RestEndpoint):
    """REST API endpoint for downloading individual assets."""

    ENDPOINT_PATH = "/api/assets/download"

    async def get(self, request: web.Request) -> web.Response:
        """Download a specific asset file via GET request."""
        asset_path = request.query.get("path")

        if not asset_path:
            return await self.invalid_request(
                message='Required query parameter "path" was not provided',
                type="error",
            )

        return await self._download(request, asset_path)

    async def post(self, request: web.Request) -> web.Response:
        """Download a specific asset file via POST request."""
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return await self.json_decode_error()

        asset_path = data.get("path")

        if not asset_path or not isinstance(asset_path, str):
            return await self.invalid_request(
                message='Required string attribute "path" was not provided',
                type="error",
            )

        return await self._download(request, asset_path)

    async def _download(self, request: web.Request, asset_path: str) -> web.Response:
        """Internal helper to download an asset given its path."""
        if asset_path.startswith(("http://", "https://")):
            try:
                image = await asyncio.to_thread(
                    open_image, asset_path, config_dir=self._ledfx.config_dir
                )
                if not image:
                    return await self.invalid_request(
                        message=f"Failed to download or validate URL: {asset_path}",
                        type="error",
                    )

                cache = get_image_cache()
                if not cache:
                    return await self.invalid_request(
                        message="Image cache not initialized",
                        type="error",
                    )

                abs_path = cache.get(asset_path)
                if not abs_path:
                    return await self.invalid_request(
                        message=f"Failed to cache URL: {asset_path}",
                        type="error",
                    )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to fetch URL %s: %s", asset_path, e)
                return await self.invalid_request(
                    message=f"Failed to fetch URL: {e}",
                    type="error",
                )
        else:
            try:
                exists, abs_path, error = assets.get_asset_or_builtin_path(
                    self._ledfx.config_dir, asset_path
                )

                if not exists:
                    return await self.invalid_request(
                        message=error or f"Asset not found: {asset_path}",
                        type="error",
                    )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to retrieve asset %s: %s", asset_path, e)
                return await self.internal_error(
                    message=f"Failed to retrieve asset: {e}"
                )

        content_type = _get_content_type(abs_path)

        return web.FileResponse(
            path=abs_path,
            headers={"Content-Type": content_type},
        )


def _get_content_type(file_path: str) -> str:
    """Determine content type from file extension."""
    ext = os.path.splitext(file_path)[1].lower()

    content_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".ico": "image/x-icon",
    }

    return content_types.get(ext, "application/octet-stream")
