"""API endpoint for listing built-in assets from LEDFX_ASSETS_PATH."""

import logging
import os

from aiohttp import web

from ledfx.api import RestEndpoint
from ledfx.assets import _list_assets_from_directory
from ledfx.consts import LEDFX_ASSETS_PATH

_LOGGER = logging.getLogger(__name__)


class AssetsFixedEndpoint(RestEndpoint):
    """REST API endpoint for listing built-in assets from LEDFX_ASSETS_PATH."""

    ENDPOINT_PATH = "/api/assets_fixed"

    async def get(self) -> web.Response:
        """List all built-in assets from LEDFX_ASSETS_PATH/gifs with metadata."""
        try:
            gifs_root = os.path.join(LEDFX_ASSETS_PATH, "gifs")
            cache_dir = os.path.join(self._ledfx.config_dir, "cache")
            assets = _list_assets_from_directory(
                gifs_root, "built-in assets", cache_dir=cache_dir
            )
            return await self.bare_request_success({"assets": assets})

        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to list built-in assets: %s", e)
            return await self.internal_error(
                message=f"Failed to list built-in assets: {e}"
            )
