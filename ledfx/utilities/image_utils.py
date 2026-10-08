"""Image utility functions for LedFx."""

import logging

from PIL import Image

_LOGGER = logging.getLogger(__name__)


def get_image_metadata(
    abs_path: str,
) -> tuple[int, int, str | None, int, bool]:
    """Return image metadata; on failure return (0, 0, None, 1, False)."""
    try:
        with Image.open(abs_path) as img:
            width, height = img.size
            img_format = img.format  # 'PNG', 'JPEG', 'GIF', 'WEBP', etc.
            n_frames = getattr(img, "n_frames", 1)
            is_animated = n_frames > 1
            return width, height, img_format, n_frames, is_animated
    except Exception as e:  # noqa: BLE001
        _LOGGER.warning("Could not read image metadata for %s: %s", abs_path, e)
        return 0, 0, None, 1, False
