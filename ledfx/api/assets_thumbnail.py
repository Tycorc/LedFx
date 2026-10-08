import asyncio
import io
import logging

from aiohttp import web
from PIL import Image

from ledfx import assets
from ledfx.api import RestEndpoint
from ledfx.utilities.security_utils import validate_pil_image
from ledfx.utils import get_image_cache

_LOGGER = logging.getLogger(__name__)

DEFAULT_THUMBNAIL_SIZE = 128
MIN_THUMBNAIL_SIZE = 16
MAX_THUMBNAIL_SIZE = 512


def _calculate_thumbnail_dimensions(width, height, size, dimension):
    """Calculate thumbnail dimensions based on the requested size and dimension mode."""
    if width <= 0 or height <= 0:
        raise ValueError(
            f"Width and height must be positive non-zero integers, got width={width}, height={height}"
        )

    if dimension == "width":
        new_width = size
        new_height = max(1, int(height * (size / width)))
    elif dimension == "height":
        new_height = size
        new_width = max(1, int(width * (size / height)))
    else:  # dimension == "max"
        if width > height:
            new_width = size
            new_height = max(1, int(height * (size / width)))
        else:
            new_height = size
            new_width = max(1, int(width * (size / height)))

    return new_width, new_height


class AssetsThumbnailEndpoint(RestEndpoint):
    """REST API endpoint for generating asset thumbnails on-demand."""

    ENDPOINT_PATH = "/api/assets/thumbnail"

    async def get(self, request: web.Request) -> web.Response:
        """Generate and return a thumbnail of an asset via GET request."""
        asset_path = request.query.get("path")

        if not asset_path:
            return await self.invalid_request(
                message='Required query parameter "path" was not provided',
                type="error",
            )

        size = request.query.get("size", str(DEFAULT_THUMBNAIL_SIZE))
        try:
            size = int(size)
            if size < MIN_THUMBNAIL_SIZE or size > MAX_THUMBNAIL_SIZE:
                return await self.invalid_request(
                    message=f"Size must be between {MIN_THUMBNAIL_SIZE} and {MAX_THUMBNAIL_SIZE} pixels",
                    type="error",
                )
        except (ValueError, TypeError, OverflowError):
            return await self.invalid_request(
                message="Size must be an integer",
                type="error",
            )

        dimension = request.query.get("dimension", "max")
        if dimension not in ("max", "width", "height"):
            return await self.invalid_request(
                message='Dimension must be "max", "width", or "height"',
                type="error",
            )

        animated = request.query.get("animated", "true").lower() == "true"

        force_refresh = request.query.get("force_refresh", "false").lower() == "true"

        return await self._generate_thumbnail(
            request, asset_path, size, dimension, animated, force_refresh
        )

    async def post(self, request: web.Request) -> web.Response:
        """Generate and return a thumbnail of an asset."""
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            return await self.json_decode_error()

        asset_path = data.get("path")
        if not asset_path:
            return await self.invalid_request(
                message='Required attribute "path" was not provided',
                type="error",
            )

        size = data.get("size", DEFAULT_THUMBNAIL_SIZE)
        try:
            size = int(size)
            if size < MIN_THUMBNAIL_SIZE or size > MAX_THUMBNAIL_SIZE:
                return await self.invalid_request(
                    message=f"Size must be between {MIN_THUMBNAIL_SIZE} and {MAX_THUMBNAIL_SIZE} pixels",
                    type="error",
                )
        except (ValueError, TypeError, OverflowError):
            return await self.invalid_request(
                message="Size must be an integer",
                type="error",
            )

        dimension = data.get("dimension", "max")
        if dimension not in ("max", "width", "height"):
            return await self.invalid_request(
                message='Dimension must be "max", "width", or "height"',
                type="error",
            )

        animated = data.get("animated", True)
        if not isinstance(animated, bool):
            return await self.invalid_request(
                message=f"Invalid animated value type: {type(animated).__name__}. Must be boolean (true/false)",
                type="error",
            )

        force_refresh = data.get("force_refresh", False)
        if not isinstance(force_refresh, bool):
            return await self.invalid_request(
                message=f"Invalid force_refresh value type: {type(force_refresh).__name__}. Must be boolean (true/false)",
                type="error",
            )

        return await self._generate_thumbnail(
            request, asset_path, size, dimension, animated, force_refresh
        )

    async def _generate_thumbnail(
        self,
        request: web.Request,
        asset_path: str,
        size: int,
        dimension: str,
        animated: bool,
        force_refresh: bool,
    ) -> web.Response:
        """Internal helper to generate a thumbnail for an asset."""
        is_cached_url = asset_path.startswith(("http://", "https://"))

        if is_cached_url:
            cache_url = asset_path
        else:
            cache_url = f"asset://{asset_path}"

        cache_params = {
            "size": size,
            "dimension": dimension,
            "animated": animated,
        }

        cache = get_image_cache()
        if cache and not force_refresh:
            cached_path = cache.get(cache_url, cache_params)
            if cached_path:
                try:
                    with open(cached_path, "rb") as f:  # noqa: ASYNC230
                        cached_data = f.read()

                    content_type = (
                        "image/webp" if cached_path.endswith(".webp") else "image/png"
                    )

                    _LOGGER.debug(
                        "Returning cached thumbnail for %s (size=%s, dimension=%s, animated=%s)",
                        asset_path,
                        size,
                        dimension,
                        animated,
                    )

                    return web.Response(
                        body=cached_data,
                        headers={"Content-Type": content_type},
                    )
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning(
                        "Failed to read cached thumbnail, regenerating: %s", e
                    )
                    cache.delete(cache_url, cache_params)

        try:
            if is_cached_url:
                from ledfx.utils import open_image

                try:
                    image = await asyncio.to_thread(
                        open_image, asset_path, config_dir=self._ledfx.config_dir
                    )
                    if not image:
                        return await self.invalid_request(
                            message=f"Failed to download or validate URL: {asset_path}",
                            type="error",
                        )

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
                exists, abs_path, error = assets.get_asset_or_builtin_path(
                    self._ledfx.config_dir, asset_path
                )

                if not exists:
                    return await self.invalid_request(
                        message=error or f"Asset not found: {asset_path}",
                        type="error",
                    )

            try:
                with Image.open(abs_path) as img:
                    is_animated_image = getattr(img, "is_animated", False)
                    n_frames = getattr(img, "n_frames", 1)

                    if animated and is_animated_image and n_frames > 1:
                        if not validate_pil_image(img):
                            return await self.invalid_request(
                                message="Animation exceeds frame or size limits",
                                type="error",
                            )
                        frames = []
                        durations = []

                        for frame_idx in range(n_frames):
                            img.seek(frame_idx)
                            frame = img.copy()

                            if frame.mode != "RGBA":
                                frame = frame.convert("RGBA")

                            width, height = frame.size
                            new_width, new_height = _calculate_thumbnail_dimensions(
                                width, height, size, dimension
                            )

                            resized_frame = frame.resize(
                                (new_width, new_height),
                                Image.Resampling.LANCZOS,
                            )
                            frames.append(resized_frame)

                            duration = img.info.get("duration", 100)
                            durations.append(duration)

                        buffer = io.BytesIO()
                        frames[0].save(
                            buffer,
                            format="WEBP",
                            save_all=True,
                            append_images=frames[1:],
                            duration=durations,
                            loop=0,
                            optimize=True,
                        )
                        buffer.seek(0)

                        thumbnail_data = buffer.read()

                        if cache and force_refresh:
                            cache.delete(cache_url, cache_params)

                        if cache:
                            try:
                                cache.put(
                                    cache_url,
                                    thumbnail_data,
                                    "image/webp",
                                    params=cache_params,
                                )
                                _LOGGER.debug(
                                    "Cached animated thumbnail for %s",
                                    asset_path,
                                )
                            except Exception as e:  # noqa: BLE001
                                _LOGGER.warning("Failed to cache thumbnail: %s", e)

                        return web.Response(
                            body=thumbnail_data,
                            headers={"Content-Type": "image/webp"},
                        )
                    else:
                        if is_animated_image and n_frames > 1:
                            img.seek(0)  # Get first frame

                        if img.mode not in ("RGB", "L"):
                            img = img.convert("RGB")

                        width, height = img.size
                        new_width, new_height = _calculate_thumbnail_dimensions(
                            width, height, size, dimension
                        )

                        img = img.resize(
                            (new_width, new_height), Image.Resampling.LANCZOS
                        )

                        buffer = io.BytesIO()
                        img.save(buffer, format="PNG", optimize=True)
                        buffer.seek(0)

                        thumbnail_data = buffer.read()

                        if cache and force_refresh:
                            cache.delete(cache_url, cache_params)

                        if cache:
                            try:
                                cache.put(
                                    cache_url,
                                    thumbnail_data,
                                    "image/png",
                                    params=cache_params,
                                )
                                _LOGGER.debug(
                                    "Cached static thumbnail for %s",
                                    asset_path,
                                )
                            except Exception as e:  # noqa: BLE001
                                _LOGGER.warning("Failed to cache thumbnail: %s", e)

                        return web.Response(
                            body=thumbnail_data,
                            headers={"Content-Type": "image/png"},
                        )

            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to generate thumbnail for %s: %s", asset_path, e
                )
                return await self.internal_error(
                    message=f"Failed to generate thumbnail: {e}"
                )

        except Exception as e:  # noqa: BLE001
            _LOGGER.warning("Failed to process thumbnail request: %s", e)
            return await self.internal_error(message=f"Failed to process request: {e}")
