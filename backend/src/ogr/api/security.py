"""API-key auth and single-use SSE stream tokens (TECHNICAL-SPEC §4.5, DP-8).

`X-API-Key` protects every route except `/health`. Browser `EventSource`
cannot send custom headers, so the two SSE routes accept a short-lived,
single-use `?token=` instead, scoped to the one query/build id it was issued
for — the long-lived key never enters a URL, browser history or an access
log.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from ogr.common.config import RunConfig, get_default_config

__all__ = ["StreamTokenStore", "get_config", "require_api_key"]


def get_config() -> RunConfig:
    """Overridable via `app.dependency_overrides[get_config]` in tests."""
    return get_default_config()


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    config: RunConfig = Depends(get_config),
) -> None:
    if not config.ogr_api_key:
        raise HTTPException(status_code=503, detail="OGR_API_KEY is not configured")
    if not x_api_key or x_api_key != config.ogr_api_key:
        raise HTTPException(status_code=401, detail="Missing or invalid X-API-Key")


@dataclass
class _Entry:
    scope_id: str
    expires_at: float
    used: bool = False


class StreamTokenStore:
    """Single-use, short-lived tokens scoped to one query_id/build_id."""

    def __init__(self, ttl_s: int = 300) -> None:
        self.ttl_s = ttl_s
        self._entries: dict[str, _Entry] = {}

    def issue(self, scope_id: str) -> str:
        token = secrets.token_urlsafe(24)
        self._entries[token] = _Entry(scope_id=scope_id, expires_at=time.monotonic() + self.ttl_s)
        return token

    def consume(self, token: str, scope_id: str) -> bool:
        """True and marks used, exactly once, iff the token matches the
        scope and has not expired or already been used."""
        entry = self._entries.get(token)
        if entry is None or entry.used or entry.scope_id != scope_id:
            return False
        if time.monotonic() > entry.expires_at:
            return False
        entry.used = True
        return True
