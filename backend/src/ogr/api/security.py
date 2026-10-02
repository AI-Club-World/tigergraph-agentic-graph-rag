"""Request dependencies shared by the API routes.

The application is open (owner's decision): there is no sign-in, API key,
role or stream token. Only the configuration dependency remains, so tests
can override it.
"""

from __future__ import annotations

from ogr.common.config import RunConfig, get_default_config

__all__ = ["get_config"]


def get_config() -> RunConfig:
    """Overridable via `app.dependency_overrides[get_config]` in tests."""
    return get_default_config()
