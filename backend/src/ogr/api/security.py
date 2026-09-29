"""Auth: sessions, roles, API keys and single-use SSE stream tokens
(TECHNICAL-SPEC §4.5, DP-8).

No secret ships in the browser bundle. The UI signs in with a key the
operator types (`POST /auth/session`) and gets a random session token,
held server-side with an expiry and revocable (`DELETE /auth/session`); it
sends that as `Authorization: Bearer`. Scripts and the CLI may send the key
itself as `X-API-Key`.

Two roles. `OGR_API_KEY` is a viewer: ask questions, read runs and history.
`OGR_ADMIN_KEY` is an admin: build/reset, uploads, embedding jobs, settings,
benchmarks and imports (`require_admin`). With no admin key configured,
`OGR_API_KEY` keeps every right. Repeated wrong keys from one client are
refused for a while (`SignInLimiter`).

Browser `EventSource` cannot send custom headers, so the two SSE routes
accept a short-lived, single-use `?token=` instead, scoped to the one
query/build id it was issued for — no key or session token enters a URL,
browser history or an access log.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from ogr.common.config import RunConfig, get_default_config

__all__ = [
    "SessionStore", "SignInLimiter", "StreamTokenStore", "get_config", "require_admin", "require_api_key",
    "role_for_key", "sessions", "sign_in_limiter",
]

ADMIN, VIEWER = "admin", "viewer"


def get_config() -> RunConfig:
    """Overridable via `app.dependency_overrides[get_config]` in tests."""
    return get_default_config()


def _same(a: str, b: str) -> bool:
    return bool(a) and bool(b) and secrets.compare_digest(a.encode(), b.encode())


def role_for_key(key: str | None, config: RunConfig) -> str | None:
    """The role a key grants, or None for a wrong key."""
    if not key:
        return None
    if _same(key, config.ogr_admin_key):
        return ADMIN
    if _same(key, config.ogr_api_key):
        return VIEWER if config.ogr_admin_key else ADMIN
    return None


class SessionStore:
    """Browser sessions: random tokens held server-side with an expiry.
    A token carries no information; losing the process ends every session."""

    def __init__(self) -> None:
        self._entries: dict[str, tuple[str, float]] = {}

    def issue(self, role: str, ttl_s: int) -> str:
        now = time.monotonic()
        self._entries = {t: e for t, e in self._entries.items() if e[1] >= now}
        token = secrets.token_urlsafe(32)
        self._entries[token] = (role, now + ttl_s)
        return token

    def role(self, token: str) -> str | None:
        entry = self._entries.get(token)
        if entry is None:
            return None
        if time.monotonic() > entry[1]:
            del self._entries[token]
            return None
        return entry[0]

    def revoke(self, token: str) -> None:
        self._entries.pop(token, None)

    def clear(self) -> None:
        self._entries.clear()


class SignInLimiter:
    """At most `limit` wrong keys per client in `window_s`; then refused
    until the window passes. Slows guessing; a correct key resets nothing."""

    def __init__(self, limit: int = 10, window_s: float = 600.0) -> None:
        self.limit, self.window_s = limit, window_s
        self._failures: dict[str, list[float]] = {}

    def blocked(self, client: str) -> bool:
        now = time.monotonic()
        recent = [t for t in self._failures.get(client, []) if now - t < self.window_s]
        self._failures[client] = recent
        return len(recent) >= self.limit

    def fail(self, client: str) -> None:
        self._failures.setdefault(client, []).append(time.monotonic())

    def clear(self) -> None:
        self._failures.clear()


sessions = SessionStore()
sign_in_limiter = SignInLimiter()


def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
    config: RunConfig = Depends(get_config),
) -> str:
    """Any signed-in role (a session or a key). Returns the role."""
    if not config.ogr_api_key:
        raise HTTPException(status_code=503, detail="OGR_API_KEY is not configured")
    if authorization and authorization.lower().startswith("bearer "):
        role = sessions.role(authorization[7:].strip())
        if role:
            return role
        raise HTTPException(status_code=401, detail="Session expired or signed out; sign in again")
    role = role_for_key(x_api_key, config)
    if role:
        return role
    raise HTTPException(status_code=401, detail="Sign in required (missing or invalid credentials)")


def require_admin(role: str = Depends(require_api_key)) -> str:
    if role != ADMIN:
        raise HTTPException(status_code=403, detail="This action needs the admin key (OGR_ADMIN_KEY)")
    return role


@dataclass
class _Entry:
    scope_id: str
    expires_at: float


class StreamTokenStore:
    """Single-use, short-lived tokens scoped to one query_id/build_id."""

    def __init__(self, ttl_s: int = 300) -> None:
        self.ttl_s = ttl_s
        self._entries: dict[str, _Entry] = {}

    def issue(self, scope_id: str) -> str:
        # Expired tokens are dropped here, and a used one in consume(), so the
        # store holds only live tokens instead of growing across a session.
        now = time.monotonic()
        self._entries = {t: e for t, e in self._entries.items() if e.expires_at >= now}
        token = secrets.token_urlsafe(24)
        self._entries[token] = _Entry(scope_id=scope_id, expires_at=time.monotonic() + self.ttl_s)
        return token

    def consume(self, token: str, scope_id: str) -> bool:
        """True and marks used, exactly once, iff the token matches the
        scope and has not expired or already been used."""
        entry = self._entries.get(token)
        if entry is None or entry.scope_id != scope_id:
            return False
        del self._entries[token]
        return time.monotonic() <= entry.expires_at
