"""API endpoints for asset management."""

import logging

from aiohttp import BodyPartReader, web

from ledfx import assets
from ledfx.api import RestEndpoint

_LOGGER = logging.getLogger(__name__)


class AssetsEndpoint(RestEndpoint):
    """REST API endpoint for asset management."""

    ENDPOINT_PATH = "/api/assets"

    async def get(self) -> web.Response:
        """List all available assets with metadata."""
        try:
            asset_list = assets.list_assets(self._ledfx.config_dir)
            return await self.bare_request_success({"assets": asset_list})
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to list assets: %s", e)
            return await self.internal_error(message=f"Failed to list assets: {e}")

    async def post(self, request: web.Request) -> web.Response:
        """Upload a new asset."""
        file_data = None
        asset_path = None

        if not request.content_type.startswith("multipart/"):
            return await self.invalid_request(
                message="Upload must be multipart/form-data"
            )
        reader = await request.multipart()
        while True:
            part = await reader.next()
            if part is None:
                break

            if not isinstance(part, BodyPartReader):
                return await self.invalid_request(
                    message="Nested multipart uploads are not supported",
                    resp_code=400,
                )

            if part.name == "file":
                file_data = await part.read(decode=False)
            elif part.name == "path":
                asset_path = (await part.read(decode=True)).decode("utf-8")

        if not file_data or not asset_path:
            return await self.invalid_request(
                message="Missing file or path",
                type="error",
            )

        success, abs_path, error = assets.save_asset(  # noqa: RUF059
            self._ledfx.config_dir,
            asset_path,
            file_data,
            allow_overwrite=True,
        )

        if not success:
            return await self.invalid_request(
                message=error or "Failed to save asset",
                type="error",
            )

        return await self.request_success(
            type="success",
            message=f"Asset uploaded: {asset_path}",
            data={"path": asset_path},
        )

    async def delete(self, request: web.Request) -> web.Response:
        """Delete an asset."""
        asset_path = request.query.get("path")

        if not asset_path:
            try:
                data = await request.json()
                asset_path = data.get("path")
            except Exception:  # noqa: BLE001, S110
                pass

        if not asset_path or not isinstance(asset_path, str):
            return await self.invalid_request(
                message="No path provided for deletion",
                type="error",
            )

        try:
            success, error = assets.delete_asset(self._ledfx.config_dir, asset_path)

            if not success:
                return await self.invalid_request(
                    message=error or f"Failed to delete asset: {asset_path}",
                    type="error",
                )

            return await self.request_success(
                type="success",
                message=f"Asset deleted: {asset_path}",
                data={"deleted": True, "path": asset_path},
            )

        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to delete asset %s: %s", asset_path, e)
            return await self.internal_error(message=f"Failed to delete asset: {e}")
