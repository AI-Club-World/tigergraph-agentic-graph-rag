"""GRAPH-06: vector-readiness gate.

Source spec: TECHNICAL-SPEC §11
Gate: G1

The vector index build is asynchronous and lags loading. Polling
`/restpp/vector/status` for `Ready_for_query` before any benchmark run is a
hard gate — starting a run against a not-yet-ready index does not error, it
silently returns incomplete results, which is the failure mode worth
refusing rather than tolerating.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from ogr.common.config import RunConfig

__all__ = ["VectorNotReadyError", "check_vector_status", "wait_until_ready"]


class VectorNotReadyError(RuntimeError):
    """Raised when the vector index never reaches Ready_for_query in time."""


def _is_ready(data: dict[str, Any]) -> bool:
    # TigerGraph 4.2+ reports the servers still rebuilding the index; an empty
    # list means every vector index is queryable. Older builds report a
    # status string or boolean.
    if isinstance(data.get("NeedRebuildServers"), list):
        return not data["NeedRebuildServers"]
    return data.get("status") == "Ready_for_query" or data.get("Ready_for_query") is True


def check_vector_status(
    config: RunConfig,
    get: Callable[..., Any] = requests.get,
    conn: Any | None = None,
) -> tuple[bool, dict[str, Any]]:
    """One poll of `/restpp/vector/status`. Returns (is_ready, raw_response).

    With a pyTigerGraph connection, the poll goes through it so every auth
    style the client supports works — RESTPP rejects a bare request made with
    username/password (REST-10016). Without one, a bearer token is required.
    """
    if conn is not None:
        data = conn.getVectorIndexStatus()
        return _is_ready(data), data
    headers = {}
    token = config.tg_token or config.tg_jwt_token
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{config.tg_host.rstrip('/')}/restpp/vector/status"
    response = get(url, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()
    return _is_ready(data), data


def wait_until_ready(
    config: RunConfig,
    timeout_s: float = 300.0,
    poll_interval_s: float = 5.0,
    get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    conn: Any | None = None,
) -> dict[str, Any]:
    """Poll until `Ready_for_query` or `timeout_s` elapses.

    Raises `VectorNotReadyError` on timeout rather than returning a falsy
    value — a caller that forgets to check a boolean is exactly how this gate
    would get silently bypassed.
    """
    deadline = time.monotonic() + timeout_s
    last_data: dict[str, Any] = {}
    while True:
        ready, last_data = check_vector_status(config, get=get, conn=conn)
        if ready:
            return last_data
        if time.monotonic() >= deadline:
            raise VectorNotReadyError(
                f"Vector index not Ready_for_query after {timeout_s}s: {last_data}"
            )
        sleep(poll_interval_s)
