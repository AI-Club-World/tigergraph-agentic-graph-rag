"""Source identity from a URL when a dataset names no source."""

from __future__ import annotations

import re

_HOST = re.compile(r"^https?://(?:www\.|[a-z]{2,3}\.)?([^/:]+)", re.IGNORECASE)


def source_of_url(url: str | None) -> tuple[str, str]:
    """`https://en.wikipedia.org/wiki/X` -> ("src:wikipedia.org", "wikipedia.org")."""
    match = _HOST.match(url or "")
    host = match.group(1).lower() if match else "unknown"
    return f"src:{host}", host
