"""Security utilities for LedFx."""

import http.client
import ipaddress
import logging
import mimetypes
import os
import socket
import urllib.parse
import urllib.request
from functools import partial

from PIL import Image

_LOGGER = logging.getLogger(__name__)


ALLOWED_IMAGE_EXTENSIONS = {
    ".gif",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".ico",
}

ALLOWED_MIME_TYPES = {
    "image/gif",
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/x-icon",
}

ALLOWED_PIL_FORMATS = {
    "GIF",
    "PNG",
    "JPEG",
    "WEBP",
    "BMP",
    "TIFF",
    "ICO",
    "PPM",
    "PGM",
    "PBM",
}


MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_IMAGE_PIXELS = 4096 * 4096  # Prevent decompression bombs
MAX_IMAGE_FRAMES = 1000
MAX_ANIMATION_PIXELS = 16 * MAX_IMAGE_PIXELS  # ~268M: 1000 x 512x512, 128 x 1080p
DOWNLOAD_TIMEOUT = 30  # seconds


ALWAYS_BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2002::/16"),  # 6to4 (RFC 3056)
    ipaddress.ip_network("2001::/32"),  # Teredo (RFC 4380)
    ipaddress.ip_network("::/96"),  # IPv4-compatible (RFC 4291, deprecated)
    ipaddress.ip_network("64:ff9b:1::/48"),
]

PRIVATE_IP_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fd00::/8"),
]

BLOCKED_IP_NETWORKS = ALWAYS_BLOCKED_IP_NETWORKS + PRIVATE_IP_NETWORKS

BLOCKED_HOSTNAMES = [
    "169.254.169.254",  # AWS, Azure, GCP metadata
    "metadata.google.internal",  # GCP
    "169.254.170.2",  # AWS ECS metadata
]


def resolve_safe_path_in_directory(
    root_dir: str,
    relative_path: str,
    create_dirs: bool = False,
    directory_name: str = "directory",
) -> tuple[bool, str | None, str | None]:
    """Resolve and validate a path within a root directory."""
    if not relative_path:
        return False, None, "Empty path provided"

    relative_path = relative_path.strip().replace("\\", "/")

    if (
        os.path.isabs(relative_path)
        or relative_path.startswith("/")
        or "://" in relative_path
    ):
        return False, None, "Absolute paths are not allowed"

    try:
        candidate_path = os.path.join(root_dir, relative_path)
        resolved_path = os.path.abspath(os.path.realpath(candidate_path))
        normalized_root = os.path.abspath(os.path.realpath(root_dir))

        try:
            common = os.path.commonpath([resolved_path, normalized_root])
            if common != normalized_root:
                return (
                    False,
                    None,
                    f"Path escapes {directory_name} directory (path traversal blocked)",
                )
        except ValueError:
            return (
                False,
                None,
                f"Path is outside {directory_name} directory (different drive/root)",
            )

        if create_dirs:
            parent_dir = os.path.dirname(resolved_path)
            if not os.path.exists(parent_dir):
                try:
                    os.makedirs(parent_dir, exist_ok=True)
                    _LOGGER.debug(
                        "Created %s subdirectory: %s",
                        directory_name,
                        parent_dir,
                    )
                except OSError as e:
                    return (
                        False,
                        None,
                        f"Failed to create parent directories: {e}",
                    )

        return True, resolved_path, None

    except (ValueError, OSError) as e:
        _LOGGER.warning("Path resolution failed for '%s': %s", relative_path, e)
        return False, None, f"Invalid path: {e}"


def validate_local_path(
    file_path: str, allowed_directories: list[str]
) -> tuple[bool, str | None]:
    """Validate that local file path is within allowed directories (path traversal
    protection).
    """
    if not allowed_directories:
        _LOGGER.warning("No allowed directories configured for path validation")
        return False, None

    try:
        abs_path = os.path.abspath(os.path.realpath(file_path))

        for allowed_dir in allowed_directories:
            abs_allowed = os.path.abspath(os.path.realpath(allowed_dir))

            try:
                common = os.path.commonpath([abs_path, abs_allowed])
                if common == abs_allowed:
                    return True, abs_path
            except ValueError:
                continue

        _LOGGER.warning(
            "Path traversal attempt blocked: %s is outside allowed directories",
            file_path,
        )
        return False, None

    except (ValueError, OSError) as e:
        _LOGGER.warning("Invalid path rejected: %s : %s", file_path, e)
        return False, None


_NAT64_WELL_KNOWN = ipaddress.ip_network("64:ff9b::/96")


def _ip_and_embedded_ipv4(
    ip_str: str,
) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Parse an IP and add any IPv4 destination embedded in an IPv6 address."""
    ip = ipaddress.ip_address(ip_str)
    candidates: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            candidates.append(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            candidates.append(ip.sixtofour)
        if ip.teredo is not None:
            candidates.extend(ip.teredo)
        if ip in _NAT64_WELL_KNOWN or ip in ipaddress.ip_network("::/96"):
            candidates.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return candidates


def _is_in_networks(
    ip_str: str,
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    return any(
        ip in network for ip in _ip_and_embedded_ipv4(ip_str) for network in networks
    )


def is_blocked_ip(ip_str: str) -> bool:
    """Check if an IP address is in the blocklist."""
    try:
        return _is_in_networks(ip_str, BLOCKED_IP_NETWORKS)
    except ValueError:
        return True


def validate_url_safety(url: str, allow_private: bool = False) -> tuple[bool, str]:
    """Validate URL scheme, host and resolved addresses; allow_private never permits
    loopback.
    """
    try:
        parsed = urllib.parse.urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False, f"Protocol '{parsed.scheme}' not allowed"

        hostname = parsed.hostname
        if not hostname:
            return False, "No hostname found in URL"

        if hostname.lower() in BLOCKED_HOSTNAMES:
            return False, f"Hostname '{hostname}' is blocked"

        try:
            addr_info = socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
        except socket.gaierror as e:
            return False, f"Failed to resolve hostname '{hostname}': {e}"

        blocked_networks = (
            ALWAYS_BLOCKED_IP_NETWORKS if allow_private else BLOCKED_IP_NETWORKS
        )

        for family, socktype, proto, canonname, sockaddr in addr_info:
            ip_str = str(sockaddr[0])
            try:
                if _is_in_networks(ip_str, blocked_networks):
                    return (
                        False,
                        f"URL resolves to blocked IP address: {ip_str}",
                    )
            except ValueError:
                return False, f"Invalid IP address resolved: {ip_str}"

        return True, ""

    except Exception as e:  # noqa: BLE001
        return False, f"URL validation error: {e}"


def _create_validated_connection(
    address: tuple[str, int],
    timeout: float | None = None,
    source_address: tuple[str, int] | None = None,
    *,
    allow_private: bool = False,
) -> socket.socket:
    """socket.create_connection that connects only to addresses it validated."""
    host, port = address
    if host.lower() in BLOCKED_HOSTNAMES:
        raise OSError(f"Hostname '{host}' is blocked")
    blocked_networks = (
        ALWAYS_BLOCKED_IP_NETWORKS if allow_private else BLOCKED_IP_NETWORKS
    )
    addr_info = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    for *_, sockaddr in addr_info:
        if _is_in_networks(str(sockaddr[0]), blocked_networks):
            raise OSError(f"'{host}' resolves to blocked IP address: {sockaddr[0]}")

    error: OSError | None = None
    for family, socktype, proto, _, sockaddr in addr_info:
        sock = socket.socket(family, socktype, proto)
        try:
            if timeout is not None:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            error = exc
            sock.close()
    raise error or OSError(f"Could not connect to '{host}'")


class _ValidatedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, allow_private: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = partial(
            _create_validated_connection, allow_private=allow_private
        )


class _ValidatedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, allow_private: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = partial(
            _create_validated_connection, allow_private=allow_private
        )


class _ValidatedHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, allow_private: bool) -> None:
        super().__init__()
        self._allow_private = allow_private

    def http_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(
            partial(_ValidatedHTTPConnection, allow_private=self._allow_private), req
        )


class _ValidatedHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, allow_private: bool) -> None:
        super().__init__()
        self._allow_private = allow_private

    def https_open(self, req: urllib.request.Request) -> http.client.HTTPResponse:
        return self.do_open(
            partial(_ValidatedHTTPSConnection, allow_private=self._allow_private),
            req,
            context=self._context,
        )


def safe_urlopen(
    request: urllib.request.Request | str,
    timeout: float,
    allow_private: bool = False,
) -> http.client.HTTPResponse:
    """urlopen that re-validates every connection, including redirects."""
    opener = urllib.request.OpenerDirector()
    for handler in (
        urllib.request.ProxyHandler({}),
        urllib.request.UnknownHandler(),
        _ValidatedHTTPHandler(allow_private),
        _ValidatedHTTPSHandler(allow_private),
        urllib.request.HTTPDefaultErrorHandler(),
        urllib.request.HTTPRedirectHandler(),
        urllib.request.HTTPErrorProcessor(),
    ):
        opener.add_handler(handler)
    return opener.open(request, timeout=timeout)


def is_allowed_image_extension(path: str) -> bool:
    """Check if file extension is in allowlist."""
    parsed = urllib.parse.urlparse(path)

    if parsed.scheme in ("http", "https") or parsed.netloc:
        path_to_check = parsed.path
    else:
        path_to_check = path

    ext = os.path.splitext(path_to_check.lower())[1]

    if parsed.scheme in ("http", "https"):
        return ext in ALLOWED_IMAGE_EXTENSIONS or not ext

    return ext in ALLOWED_IMAGE_EXTENSIONS


def validate_image_mime_type(file_path: str) -> bool:
    """Validate MIME type after validate_local_path has constrained the file path."""
    try:
        with Image.open(file_path) as img:
            if img.format is None:
                return False

            if img.format.upper() not in ALLOWED_PIL_FORMATS:
                return False

        mime_type, _ = mimetypes.guess_type(file_path)
        return not (mime_type and mime_type not in ALLOWED_MIME_TYPES)
    except Exception:  # noqa: BLE001
        return False


def validate_pil_image(image: Image.Image) -> bool:
    """Check image format, dimensions, animation frame count and total decoded
    pixels.
    """
    if image.format not in ALLOWED_PIL_FORMATS:
        _LOGGER.warning("Rejected unsupported image format: %s", image.format)
        return False

    if image.width * image.height > MAX_IMAGE_PIXELS:
        _LOGGER.warning(
            "Image too large: %sx%s pixels (max %s)",
            image.width,
            image.height,
            MAX_IMAGE_PIXELS,
        )
        return False

    try:
        n_frames = getattr(image, "n_frames", 1)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Could not count image frames")
        return False
    if n_frames > MAX_IMAGE_FRAMES:
        _LOGGER.warning("Too many frames: %s (max %s)", n_frames, MAX_IMAGE_FRAMES)
        return False
    if n_frames * image.width * image.height > MAX_ANIMATION_PIXELS:
        _LOGGER.warning(
            "Animation too large: %s frames of %sx%s (max %s total pixels)",
            n_frames,
            image.width,
            image.height,
            MAX_ANIMATION_PIXELS,
        )
        return False

    return True


def build_browser_request(url: str) -> urllib.request.Request:
    """Build a URL request with browser-like headers to avoid hotlink blocking."""
    parsed = urllib.parse.urlsplit(url)
    origin = (
        f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/141.0.0.0 Safari/537.36"
        ),
        "Referer": origin,  # helps with sites that block direct hotlinks (e.g., JSTOR)
    }
    return urllib.request.Request(url, headers=headers)
