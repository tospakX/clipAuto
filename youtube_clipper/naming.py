"""Cross-platform-safe names for video directories and clip files."""

from __future__ import annotations

import re
import unicodedata

_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_UNSAFE_RUN = re.compile(r"[^a-z0-9._-]+")
_SEPARATOR_RUN = re.compile(r"[-_.]{2,}")


def _is_windows_reserved(value: str) -> bool:
    return value.split(".", 1)[0] in _WINDOWS_RESERVED


def safe_component(value: str, fallback: str, max_length: int = 80) -> str:
    """Return a bounded filename component valid on common Linux and Windows filesystems."""
    if max_length < 1:
        raise ValueError("max_length must be positive")
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    )
    result = _UNSAFE_RUN.sub("-", ascii_value).strip(" ._-")
    result = _SEPARATOR_RUN.sub("-", result)
    if not result or _is_windows_reserved(result):
        fallback_ascii = (
            unicodedata.normalize("NFKD", fallback)
            .encode("ascii", "ignore")
            .decode("ascii")
            .lower()
        )
        result = _UNSAFE_RUN.sub("-", fallback_ascii).strip(" ._-") or "item"
        result = _SEPARATOR_RUN.sub("-", result)
        if _is_windows_reserved(result):
            result = "item"
    result = result[:max_length].rstrip(" ._-")
    return result or "item"


def video_directory_name(title: str, video_id: str, max_length: int = 96) -> str:
    """Build a readable directory name whose ID suffix prevents title collisions."""
    safe_id = safe_component(video_id, "video", 24)
    title_length = max(1, max_length - len(safe_id) - 1)
    safe_title = safe_component(title, "video", title_length)
    return f"{safe_title}-{safe_id}"
