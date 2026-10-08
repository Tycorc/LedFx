"""Image caching system for LedFx."""

import contextlib
import functools
import hashlib
import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Concatenate, ParamSpec, TypeVar

from ledfx.utilities.gradient_extraction import extract_gradient_metadata
from ledfx.utilities.image_utils import get_image_metadata

_LOGGER = logging.getLogger(__name__)


_P = ParamSpec("_P")
_R = TypeVar("_R")


def _locked(
    method: "Callable[Concatenate[ImageCache, _P], _R]",
) -> "Callable[Concatenate[ImageCache, _P], _R]":
    """Image loads run in worker threads (asyncio.to_thread) as well as on the loop,
    and every public method reads or rewrites the shared metadata.
    """

    @functools.wraps(method)
    def wrapper(self: "ImageCache", *args: _P.args, **kwargs: _P.kwargs) -> _R:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class ImageCache:
    """Persistent image cache with LRU limits and explicit refresh; no TTL."""

    def __init__(
        self,
        config_dir: str,
        max_size_mb: int = 500,
        max_items: int = 500,
    ):
        """Initialize image cache."""
        self.cache_dir = os.path.join(config_dir, "cache", "images")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.metadata_file = os.path.join(self.cache_dir, "metadata.json")
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_items = max_items
        # ponytail: one lock for all metadata; per-key locks if it contends.
        self._lock = threading.RLock()
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> dict:
        """Load cache metadata from disk."""
        if os.path.exists(self.metadata_file):
            try:
                with open(self.metadata_file) as f:
                    return json.load(f)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning("Failed to load cache metadata: %s", e)
                return {"cache_entries": {}, "total_size": 0, "total_count": 0}
        return {"cache_entries": {}, "total_size": 0, "total_count": 0}

    def _save_metadata(self):
        """Save cache metadata to disk."""
        try:
            with open(self.metadata_file, "w") as f:
                json.dump(self.metadata, f, indent=2)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to save cache metadata: %s", e)

    def _generate_cache_key(self, url: str, params: dict | None = None) -> str:
        """Hash URL and sorted parameters so thumbnail variants have distinct keys."""
        if params:
            sorted_params = sorted(params.items())
            key_str = f"{url}|{sorted_params}"
        else:
            key_str = url
        return hashlib.sha256(key_str.encode("utf-8")).hexdigest()

    def _get_cache_path(self, cache_key: str, extension: str = ".jpg") -> str:
        """Get filesystem path for cached image."""
        return os.path.join(self.cache_dir, f"{cache_key}{extension}")

    @_locked
    def get(self, url: str, params: dict | None = None) -> str | None:
        """Get cached image if available (no expiration check)."""
        cache_key = self._generate_cache_key(url, params)
        entry = self.metadata["cache_entries"].get(cache_key)

        if entry:
            cache_path = self._get_cache_path(cache_key, entry["extension"])
            if os.path.exists(cache_path):
                entry["last_accessed"] = datetime.now(UTC).isoformat()
                entry["access_count"] = entry.get("access_count", 0) + 1
                self._save_metadata()
                _LOGGER.debug("Cache hit for %s", url)
                return cache_path

        _LOGGER.debug("Cache miss for %s", url)
        return None

    def put(
        self,
        url: str,
        data: bytes,
        content_type: str,
        etag: str | None = None,
        last_modified: str | None = None,
        params: dict | None = None,
    ):
        """Store image in cache with extracted metadata."""
        cache_key = self._generate_cache_key(url, params)

        extension_map = {
            "image/gif": ".gif",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
            "image/tiff": ".tiff",
            "image/x-icon": ".ico",
        }
        extension = extension_map.get(content_type, ".jpg")

        cache_path = self._get_cache_path(cache_key, extension)
        # A private file per call: concurrent puts for one key must not
        # interleave bytes. The rename under the lock publishes it together
        # with its metadata entry.
        tmp_path = f"{cache_path}.{threading.get_ident()}.tmp"

        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to write cache file %s: %s", cache_path, e)
            return

        now = datetime.now(UTC).isoformat()

        width, height, img_format, n_frames, is_animated = get_image_metadata(tmp_path)

        gradient_data = None
        if params is None:
            try:
                gradient_data = extract_gradient_metadata(tmp_path)
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to extract gradients for %s: %s",
                    url,
                    e,
                    exc_info=False,
                )

        entry = {
            "url": url,
            "cached_at": now,
            "last_accessed": now,
            "access_count": 1,
            "file_size": len(data),
            "etag": etag,
            "last_modified": last_modified,
            "content_type": content_type,
            "extension": extension,
            "params": params,  # Store params for reference
            "width": width,
            "height": height,
            "format": img_format,
            "n_frames": n_frames,
            "is_animated": is_animated,
            "gradients": gradient_data,
        }

        # Only the shared metadata is locked: the event loop calls get()
        # directly, so it must never wait on the image work above.
        with self._lock:
            try:
                os.replace(tmp_path, cache_path)
            except OSError as e:
                _LOGGER.error("Failed to write cache file %s: %s", cache_path, e)
                with contextlib.suppress(OSError):
                    os.remove(tmp_path)
                return

            old = self.metadata["cache_entries"].get(cache_key)
            if old is not None:
                self.metadata["total_size"] -= old["file_size"]
                self.metadata["total_count"] -= 1
                if old["extension"] != extension:
                    # Same URL, new content type: the old file is no longer
                    # referenced by any entry, so eviction would never reach it.
                    with contextlib.suppress(OSError):
                        os.remove(self._get_cache_path(cache_key, old["extension"]))

            self.metadata["cache_entries"][cache_key] = entry
            self.metadata["total_size"] += len(data)
            self.metadata["total_count"] += 1

            self._save_metadata()
            self._enforce_limits()

        _LOGGER.info("Cached image from %s (%s bytes)", url, len(data))

    def _enforce_limits(self):
        """Evict LRU entries if cache exceeds size or count limits."""
        evicted = False
        while (
            self.metadata["total_size"] > self.max_size_bytes
            or self.metadata["total_count"] > self.max_items
        ):
            if not self.metadata["cache_entries"]:
                break

            lru_key = min(
                self.metadata["cache_entries"].items(),
                key=lambda x: (
                    x[1]["last_accessed"],
                    x[1].get("access_count", 0),
                ),
            )[0]

            _LOGGER.info(
                "Evicting LRU cache entry: %s",
                self.metadata["cache_entries"][lru_key]["url"],
            )
            self._delete(lru_key)
            evicted = True

        if evicted:
            self._save_metadata()

    def _delete(self, cache_key: str):
        """Remove entry from cache by cache key."""
        if cache_key in self.metadata["cache_entries"]:
            entry = self.metadata["cache_entries"][cache_key]
            cache_path = self._get_cache_path(cache_key, entry["extension"])

            if os.path.exists(cache_path):
                try:
                    os.remove(cache_path)
                except Exception as e:  # noqa: BLE001
                    _LOGGER.warning("Failed to delete cache file %s: %s", cache_path, e)

            self.metadata["total_size"] -= entry["file_size"]
            self.metadata["total_count"] -= 1
            del self.metadata["cache_entries"][cache_key]

    @_locked
    def delete(self, url: str, params: dict | None = None) -> bool:
        """Remove specific URL (and params) from cache."""
        cache_key = self._generate_cache_key(url, params)
        if cache_key in self.metadata["cache_entries"]:
            _LOGGER.info("Deleting cached image: %s (params: %s)", url, params)
            self._delete(cache_key)
            self._save_metadata()
            return True
        return False

    @_locked
    def delete_all_for_url(self, url: str) -> int:
        """Remove all cache entries for a given URL (regardless of params). Useful
        for clearing all thumbnail variations of an asset.
        """
        deleted_count = 0
        keys_to_delete = []

        for cache_key, entry in self.metadata["cache_entries"].items():
            if entry["url"] == url:
                keys_to_delete.append(cache_key)

        for cache_key in keys_to_delete:
            self._delete(cache_key)
            deleted_count += 1

        if deleted_count > 0:
            self._save_metadata()
            _LOGGER.info("Deleted %s cache entries for URL: %s", deleted_count, url)

        return deleted_count

    @_locked
    def clear(self) -> dict:
        """Clear entire cache."""
        cleared_count = len(self.metadata["cache_entries"])
        freed_bytes = self.metadata["total_size"]

        for cache_key in list(self.metadata["cache_entries"].keys()):
            self._delete(cache_key)

        self._save_metadata()
        _LOGGER.info(
            "Cleared entire cache: %s items, %s bytes",
            cleared_count,
            freed_bytes,
        )

        return {"cleared_count": cleared_count, "freed_bytes": freed_bytes}

    @_locked
    def get_stats(self) -> dict:
        """Return cache totals and image metadata, excluding thumbnail variants."""
        entries = [
            {
                "url": entry["url"],
                "cached_at": entry["cached_at"],
                "last_accessed": entry["last_accessed"],
                "access_count": entry.get("access_count", 0),
                "file_size": entry["file_size"],
                "content_type": entry.get("content_type", "unknown"),
                "width": entry.get("width", 0),
                "height": entry.get("height", 0),
                "format": entry.get("format"),
                "n_frames": entry.get("n_frames", 1),
                "is_animated": entry.get("is_animated", False),
                "gradients": entry.get("gradients"),
            }
            for entry in self.metadata["cache_entries"].values()
            if not entry["url"].startswith("asset://") and entry.get("params") is None
        ]

        entries.sort(key=lambda x: x["access_count"], reverse=True)

        return {
            "total_size": self.metadata["total_size"],
            "total_count": self.metadata["total_count"],
            "max_size": self.max_size_bytes,
            "max_count": self.max_items,
            "entries": entries,
        }

    @_locked
    def get_cache_headers(self, url: str, params: dict | None = None) -> dict | None:
        """Get stored ETag and Last-Modified headers for conditional requests."""
        cache_key = self._generate_cache_key(url, params)
        entry = self.metadata["cache_entries"].get(cache_key)

        if entry:
            return {
                "etag": entry.get("etag"),
                "last_modified": entry.get("last_modified"),
            }
        return None
