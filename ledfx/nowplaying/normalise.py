"""Shared metadata normalisation helpers for the Now Playing subsystem."""

import re

_TOPIC_RE = re.compile(r"\s*-\s*topic\s*$", re.IGNORECASE)

_VEVO_RE = re.compile(r"vevo\s*$", re.IGNORECASE)

_ARTIST_CHANNEL_SUFFIX_RE = re.compile(
    r"\s*(?:official|music|records|recordings|entertainment|channel|tv)\s*$",
    re.IGNORECASE,
)

_TITLE_NOISE_RE = re.compile(
    r"\s*[\(\[]"
    r"\s*(?:[^\)\]]*\bofficial\b[^\)\]]*"
    r"|[^\)\]]*\bvideo\b[^\)\]]*"
    r"|lyrics?"
    r"|visuali[zs]er?"
    r"|audio"
    r")\s*[\)\]]\s*$",
    re.IGNORECASE,
)

_TITLE_OFFICIAL_VIDEO_CUTOFF_RE = re.compile(
    r"\s*[\(\[]"
    r"\s*(?:[^\)\]]*\bofficial\b[^\)\]]*"
    r"|[^\)\]]*\bvideo\b[^\)\]]*)"
    r"\s*[\)\]].*$",
    re.IGNORECASE,
)

_QUALITY_TAG_RE = re.compile(
    r"\s*[\(\[]\s*"
    r"(?:\d{3,4}[pP]"  # 720p, 1080p, 4320p
    r"|[248][kK]"  # 4K, 2K, 8K
    r"|[hH][dD]"  # HD
    r"|[hH][qQ]"  # HQ
    r"|[fF][hH][dD]"  # FHD
    r"|[uU][hH][dD]"  # UHD
    r")"
    r"\s*[\)\]]\s*$",
    re.IGNORECASE,
)

_VERSION_SUFFIX_RE = re.compile(
    r"\s*[\(\[]\s*"
    r"(?:"
    r"(?:\d{4}\s+)?remaster(?:ed)?"
    r"|remastered\s+version"
    r"|remaster(?:ed)?\s+\d{4}"
    r"|single\s+version"
    r"|album\s+version"
    r"|radio\s+edit"
    r"|edit"
    r")"
    r"\s*[\)\]]\s*$",
    re.IGNORECASE,
)

_TITLE_UNBRACKETED_NOISE_RE = re.compile(
    r"\s*[-\u2013\u2014]\s*"
    r"(?:official\s+(?:video|audio|music\s+video|lyric\s+video|visuali[zs]er?)"
    r"|lyric\s+video"
    r"|lyrics?\s+video"
    r")\s*$",
    re.IGNORECASE,
)

_COLLAB_CONNECTOR_RE = re.compile(r"\b(?:feat|ft|x|and|with)\b")

_TITLE_CHANNEL_PREFIX_RE = re.compile(
    r"^(?:topic|vevo)\s*[-\u2013\u2014]\s*",
    re.IGNORECASE,
)

_EMPTY_ALBUMS = {
    "",
    "unknown",
    "unknown album",
    "none",
    "n/a",
    "null",
}


def _clean_spaces(value: str) -> str:
    """Collapse repeated whitespace and trim."""
    return re.sub(r"\s+", " ", value).strip()


def _normalise_compare(value: str | None) -> str:
    """Normalise a string for case-insensitive / punctuation-agnostic comparison."""
    if not value:
        return ""
    value = value.lower()
    value = re.sub(r"['`\u00b4]", "'", value)
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return _clean_spaces(value)


def _split_camel_case(value: str) -> str:
    """Insert spaces at camelCase boundaries."""
    value = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value)
    value = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", value)
    return value.strip()


def _strip_title_suffixes(title: str) -> str:
    """Iteratively strip known YouTube/version suffixes from the end of a title."""
    prev = None
    while prev != title:
        prev = title
        title = _TITLE_OFFICIAL_VIDEO_CUTOFF_RE.sub("", title).strip()
        title = _QUALITY_TAG_RE.sub("", title).strip()
        title = _TITLE_NOISE_RE.sub("", title).strip()
        title = _TITLE_UNBRACKETED_NOISE_RE.sub("", title).strip()
        title = _VERSION_SUFFIX_RE.sub("", title).strip()
    return title


def normalise_artist(artist: str | None) -> str:
    """Normalise a YouTube-style artist/channel name."""
    if not artist:
        return ""

    artist = _clean_spaces(artist)

    artist = _TOPIC_RE.sub("", artist).strip()

    if _VEVO_RE.search(artist):
        artist = _VEVO_RE.sub("", artist).strip()
        if " " not in artist:
            artist = _split_camel_case(artist)

    prev = None
    while prev != artist:
        prev = artist
        artist = _ARTIST_CHANNEL_SUFFIX_RE.sub("", artist).strip()

    if " " not in artist:
        artist = _split_camel_case(artist)

    return _clean_spaces(artist)


def normalise_title(title: str | None, artist: str = "") -> str:
    """Remove YouTube/video/release noise from a track title."""
    if not title:
        return ""

    title = _clean_spaces(title)
    artist = normalise_artist(artist)

    title = _strip_title_suffixes(title)

    if artist:
        title = re.sub(
            rf"^{re.escape(artist)}\s*[-\u2013\u2014:]\s*",
            "",
            title,
            flags=re.IGNORECASE,
        ).strip()

    parts = re.split(r"\s+[-\u2013\u2014]\s+", title, maxsplit=1)
    if len(parts) == 2:
        left = normalise_artist(parts[0])
        if artist and _normalise_compare(left) == _normalise_compare(artist):
            title = parts[1].strip()
        elif artist:
            left_cmp = _normalise_compare(parts[0])
            artist_cmp = _normalise_compare(artist)
            suffix = left_cmp[len(artist_cmp) :]
            if left_cmp.startswith(artist_cmp + " ") and _COLLAB_CONNECTOR_RE.search(
                suffix
            ):
                title = parts[1].strip()

    title = _TITLE_CHANNEL_PREFIX_RE.sub("", title).strip()

    title = _strip_title_suffixes(title)
    return _clean_spaces(title)


def normalise_album(album: str | None) -> str | None:
    """Return None for placeholder album values, otherwise the cleaned string."""
    if album is None:
        return None
    album = _clean_spaces(album)
    if album.lower() in _EMPTY_ALBUMS:
        return None
    return album
