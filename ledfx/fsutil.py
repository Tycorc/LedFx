import contextlib
import os


def fsync_directory(directory: str | os.PathLike[str]) -> None:
    """Persist a directory entry after rename on POSIX; ignore errors and Windows."""
    if os.name == "nt":
        return
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
