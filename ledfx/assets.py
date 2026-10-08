"""Secure asset storage system for LedFx."""

import io
import json
import logging
import mimetypes
import os
import tempfile
from datetime import UTC, datetime

from PIL import Image

from ledfx.consts import LEDFX_ASSETS_PATH
from ledfx.fsutil import fsync_directory
from ledfx.utilities.gradient_extraction import extract_gradient_metadata
from ledfx.utilities.image_utils import get_image_metadata
from ledfx.utilities.security_utils import (
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    resolve_safe_path_in_directory,
    validate_pil_image,
)
from ledfx.utils import get_image_cache

_LOGGER = logging.getLogger(__name__)

ASSETS_DIRECTORY = "assets"  # Directory name under .ledfx/

DEFAULT_MAX_ASSET_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

ASSET_METADATA_CACHE_FILE = ".asset_metadata_cache.json"

IGNORED_FILES = {
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
    ASSET_METADATA_CACHE_FILE,
}


def get_assets_directory(config_dir: str) -> str:
    """Get the absolute path to the assets directory."""
    return os.path.join(os.path.abspath(config_dir), ASSETS_DIRECTORY)


def ensure_assets_directory(config_dir: str) -> None:
    """Ensure the assets directory exists, creating it if necessary."""
    assets_dir = get_assets_directory(config_dir)

    if not os.path.exists(assets_dir):
        try:
            os.makedirs(assets_dir, exist_ok=True)
            _LOGGER.info("Created assets directory: %s", assets_dir)
        except OSError as e:
            _LOGGER.warning("Failed to create assets directory: %s", e)
            raise


def _load_asset_metadata_cache(assets_dir: str) -> dict:
    """Load asset metadata cache from disk."""
    cache_path = os.path.join(assets_dir, ASSET_METADATA_CACHE_FILE)

    if not os.path.exists(cache_path):
        return {}

    try:
        with open(cache_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to load asset metadata cache: %s", e)
        return {}


def _save_asset_metadata_cache(assets_dir: str, cache: dict) -> None:
    """Save asset metadata cache to disk."""
    cache_path = os.path.join(assets_dir, ASSET_METADATA_CACHE_FILE)

    try:
        os.makedirs(assets_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2)
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to save asset metadata cache: %s", e)


def resolve_safe_asset_path(
    config_dir: str, relative_path: str, create_dirs: bool = False
) -> tuple[bool, str | None, str | None]:
    """Resolve and validate an asset path, ensuring it stays within the assets
    directory.
    """
    assets_root = get_assets_directory(config_dir)
    return resolve_safe_path_in_directory(
        assets_root, relative_path, create_dirs, "assets"
    )


def validate_asset_extension(file_path: str) -> tuple[bool, str | None]:
    """Validate that the file has an allowed image extension for asset storage."""
    _, ext = os.path.splitext(file_path)
    ext_lower = ext.lower()

    if ext_lower not in ALLOWED_IMAGE_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_EXTENSIONS))
        return (
            False,
            f"File extension '{ext}' not allowed. Allowed: {allowed}",
        )

    return True, None


def validate_asset_content(
    data: bytes, file_path: str
) -> tuple[bool, str | None, Image.Image | None]:
    """Validate that the file content is a real image using Pillow."""
    try:
        image = Image.open(io.BytesIO(data))

        if not validate_pil_image(image):
            return (
                False,
                "Image validation failed (invalid format or dimensions)",
                None,
            )

        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type and mime_type not in ALLOWED_MIME_TYPES:
            return (
                False,
                f"Invalid MIME type: {mime_type} (not in allowed list)",
                None,
            )

        _, ext = os.path.splitext(file_path)
        ext_lower = ext.lower().lstrip(".")

        pil_format = image.format
        if pil_format:
            format_extensions = {
                "JPEG": {"jpg", "jpeg"},
                "PNG": {"png"},
                "WEBP": {"webp"},
                "GIF": {"gif"},
            }

            expected_exts = format_extensions.get(pil_format.upper(), set())
            if expected_exts and ext_lower not in expected_exts:
                return (
                    False,
                    f"Extension mismatch: file has .{ext_lower} but contains {pil_format} data",
                    None,
                )

        return True, None, image

    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Image validation failed for %s: %s", file_path, e)
        return False, f"Not a valid image file: {e}", None


def validate_asset_size(
    data: bytes, max_size: int = DEFAULT_MAX_ASSET_SIZE_BYTES
) -> tuple[bool, str | None]:
    """Validate that the asset size is within the allowed limit."""
    size = len(data)

    if size > max_size:
        max_mb = max_size / (1024 * 1024)
        actual_mb = size / (1024 * 1024)
        return (
            False,
            f"File too large: {actual_mb:.2f}MB (max {max_mb:.2f}MB)",
        )

    return True, None


def save_asset(
    config_dir: str,
    relative_path: str,
    data: bytes,
    max_size: int = DEFAULT_MAX_ASSET_SIZE_BYTES,
    allow_overwrite: bool = False,
) -> tuple[bool, str | None, str | None]:
    """Securely save an asset file with full validation and atomic write."""
    try:
        ensure_assets_directory(config_dir)
    except OSError as e:
        return False, None, f"Assets directory error: {e}"

    is_valid, absolute_path, error = resolve_safe_asset_path(
        config_dir, relative_path, create_dirs=True
    )
    if not is_valid:
        _LOGGER.warning("Path validation failed: %s", error)
        return False, None, error

    is_valid, error = validate_asset_extension(absolute_path)
    if not is_valid:
        _LOGGER.warning("Extension validation failed: %s", error)
        return False, None, error

    if not allow_overwrite and os.path.exists(absolute_path):
        return (
            False,
            None,
            f"File already exists: {relative_path} (overwrite not allowed)",
        )

    is_valid, error = validate_asset_size(data, max_size)
    if not is_valid:
        _LOGGER.warning("Size validation failed: %s", error)
        return False, None, error

    is_valid, error, image = validate_asset_content(data, absolute_path)
    if not is_valid:
        _LOGGER.warning("Content validation failed: %s", error)
        return False, None, error

    if image:
        image.close()

    parent_dir = os.path.dirname(absolute_path)
    temp_fd = None
    temp_path = None

    try:
        temp_fd, temp_path = tempfile.mkstemp(
            suffix=".tmp", dir=parent_dir, prefix=".asset_"
        )

        os.write(temp_fd, data)
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = None  # Mark as closed

        if os.name == "nt" and os.path.exists(absolute_path):
            os.remove(absolute_path)

        os.rename(temp_path, absolute_path)
        temp_path = None  # Mark as moved
        fsync_directory(parent_dir)  # persist the rename itself

        _LOGGER.info("Saved asset: %s (%s bytes)", relative_path, len(data))

        try:
            cache = get_image_cache()
            if cache:
                cache_url = f"asset://{relative_path}"
                deleted_count = cache.delete_all_for_url(cache_url)
                if deleted_count > 0:
                    _LOGGER.info(
                        "Cleared %s cached thumbnail(s) for %s",
                        deleted_count,
                        relative_path,
                    )
        except Exception as e:  # noqa: BLE001
            _LOGGER.warning(
                "Failed to clear cached thumbnails for %s: %s",
                relative_path,
                e,
            )

        return True, absolute_path, None

    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to save asset %s: %s", relative_path, e)
        return False, None, f"Write failed: {e}"

    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except Exception:  # noqa: BLE001, S110
                pass

        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to clean up temp file %s: %s", temp_path, e)


def delete_asset(config_dir: str, relative_path: str) -> tuple[bool, str | None]:
    """Securely delete an asset file."""
    is_valid, absolute_path, error = resolve_safe_asset_path(
        config_dir, relative_path, create_dirs=False
    )
    if not is_valid:
        _LOGGER.warning("Path validation failed for delete: %s", error)
        return False, error

    if not os.path.exists(absolute_path):
        return False, f"Asset not found: {relative_path}"

    if not os.path.isfile(absolute_path):
        return False, f"Not a file: {relative_path}"

    try:
        os.remove(absolute_path)
        _LOGGER.info("Deleted asset: %s", relative_path)

        assets_dir = get_assets_directory(config_dir)
        metadata_cache = _load_asset_metadata_cache(assets_dir)
        cache_key = relative_path.replace("\\", "/")
        if cache_key in metadata_cache:
            del metadata_cache[cache_key]
            _save_asset_metadata_cache(assets_dir, metadata_cache)

        _cleanup_empty_directories(config_dir, os.path.dirname(absolute_path))

        return True, None

    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Failed to delete asset %s: %s", relative_path, e)
        return False, f"Delete failed: {e}"


def _cleanup_empty_directories(config_dir: str, dir_path: str) -> None:
    """Remove empty directories up to (but not including) the assets root."""
    assets_root = get_assets_directory(config_dir)

    current = dir_path
    while current and current != assets_root:
        try:
            if os.path.isdir(current) and not os.listdir(current):
                os.rmdir(current)
                _LOGGER.debug("Removed empty directory: %s", current)
                current = os.path.dirname(current)
            else:
                break
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Could not remove directory %s: %s", current, e)
            break


def _list_assets_from_directory(
    root_dir: str, log_prefix: str = "assets", cache_dir: str | None = None
) -> list[dict]:
    """List all image assets in a directory recursively with metadata."""
    if not os.path.exists(root_dir):
        _LOGGER.debug(
            "%s directory does not exist: %s",
            log_prefix.capitalize(),
            root_dir,
        )
        return []

    assets = []

    cache_location = cache_dir if cache_dir is not None else root_dir

    metadata_cache = _load_asset_metadata_cache(cache_location)
    cache_updated = False

    try:
        for root, _dirs, files in os.walk(root_dir):
            for filename in files:
                if filename in IGNORED_FILES:
                    continue

                if filename.endswith(".tmp") or filename.startswith(".asset_"):
                    continue

                abs_path = os.path.join(root, filename)

                rel_path = os.path.relpath(abs_path, root_dir)

                rel_path = rel_path.replace("\\", "/")

                _, ext = os.path.splitext(filename)
                if ext.lower() not in ALLOWED_IMAGE_EXTENSIONS:
                    _LOGGER.debug(
                        "Skipping non-image file in %s: %s",
                        log_prefix,
                        rel_path,
                    )
                    continue

                try:
                    stat_info = os.stat(abs_path)
                    file_size = stat_info.st_size
                    modified_time = datetime.fromtimestamp(
                        stat_info.st_mtime, tz=UTC
                    ).isoformat()

                    width, height, img_format, n_frames, is_animated = (
                        get_image_metadata(abs_path)
                    )

                    gradient_data = None
                    cached_entry = metadata_cache.get(rel_path)

                    if (
                        cached_entry
                        and cached_entry.get("modified_time") == modified_time
                    ):
                        gradient_data = cached_entry.get("gradients")
                        _LOGGER.debug(
                            "Using cached metadata for %s %s",
                            log_prefix,
                            rel_path,
                        )
                    else:
                        try:
                            gradient_data = extract_gradient_metadata(abs_path)
                            metadata_cache[rel_path] = {
                                "gradients": gradient_data,
                                "modified_time": modified_time,
                            }
                            cache_updated = True
                        except Exception as e:  # noqa: BLE001
                            _LOGGER.warning(
                                "Failed to extract gradients for %s %s: %s",
                                log_prefix,
                                rel_path,
                                e,
                                exc_info=False,
                            )
                            metadata_cache[rel_path] = {
                                "gradients": None,
                                "modified_time": modified_time,
                            }
                            cache_updated = True

                    assets.append(
                        {
                            "path": rel_path,
                            "size": file_size,
                            "modified": modified_time,
                            "width": width,
                            "height": height,
                            "format": img_format,
                            "n_frames": n_frames,
                            "is_animated": is_animated,
                            "gradients": gradient_data,
                        }
                    )

                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning(
                        "Could not get metadata for %s %s: %s",
                        log_prefix,
                        rel_path,
                        e,
                    )
                    continue

        assets.sort(key=lambda x: x["path"])

        _LOGGER.debug("Listed %s %s with metadata", len(assets), log_prefix)

        if cache_updated:
            _save_asset_metadata_cache(cache_location, metadata_cache)

    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Error listing %s: %s", log_prefix, e)

    return assets


def list_assets(config_dir: str) -> list[dict]:
    """List all assets in the assets directory recursively with metadata."""
    assets_root = get_assets_directory(config_dir)
    return _list_assets_from_directory(assets_root, "assets")


def get_asset_path(
    config_dir: str, relative_path: str
) -> tuple[bool, str | None, str | None]:
    """Get the absolute path to an existing asset file."""
    is_valid, absolute_path, error = resolve_safe_asset_path(
        config_dir, relative_path, create_dirs=False
    )
    if not is_valid:
        return False, None, error

    if not os.path.exists(absolute_path):
        return False, None, f"Asset not found: {relative_path}"

    if not os.path.isfile(absolute_path):
        return False, None, f"Not a file: {relative_path}"

    return True, absolute_path, None


def get_asset_or_builtin_path(
    config_dir: str, relative_path: str
) -> tuple[bool, str | None, str | None]:
    """Get the absolute path to an asset file from either user assets or built-in
    assets.
    """
    if relative_path.startswith("builtin://"):
        actual_path = relative_path[10:]  # Remove "builtin://" prefix
        gifs_root = os.path.join(LEDFX_ASSETS_PATH, "gifs")

        is_valid, resolved_path, error = resolve_safe_path_in_directory(
            gifs_root,
            actual_path,
            create_dirs=False,
            directory_name="built-in assets",
        )

        if not is_valid:
            return False, None, error

        if not os.path.exists(resolved_path):
            return False, None, f"Built-in asset not found: {actual_path}"

        if not os.path.isfile(resolved_path):
            return False, None, f"Not a file: {actual_path}"

        return True, resolved_path, None

    return get_asset_path(config_dir, relative_path)
