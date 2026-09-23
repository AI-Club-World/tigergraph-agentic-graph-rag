"""Tests for GRAPH-06's vector-readiness gate — no live TigerGraph, HTTP is stubbed."""

from __future__ import annotations

import pytest

from ogr.common.config import RunConfig
from ogr.graph.vector_status import VectorNotReadyError, check_vector_status, wait_until_ready


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _config() -> RunConfig:
    return RunConfig(tg_host="https://example.i.tgcloud.io", tg_token="abc")


class TestCheckVectorStatus:
    def test_ready_status_string_is_recognised(self):
        def fake_get(url, headers=None, timeout=None):
            assert url.endswith("/restpp/vector/status")
            assert headers.get("Authorization") == "Bearer abc"
            return _FakeResponse({"status": "Ready_for_query"})

        ready, data = check_vector_status(_config(), get=fake_get)
        assert ready is True
        assert data["status"] == "Ready_for_query"

    def test_ready_for_query_boolean_field_is_also_recognised(self):
        def fake_get(url, headers=None, timeout=None):
            return _FakeResponse({"Ready_for_query": True})

        ready, _ = check_vector_status(_config(), get=fake_get)
        assert ready is True

    def test_not_ready_is_false(self):
        def fake_get(url, headers=None, timeout=None):
            return _FakeResponse({"status": "Building"})

        ready, _ = check_vector_status(_config(), get=fake_get)
        assert ready is False


class TestWaitUntilReady:
    def test_returns_as_soon_as_ready(self):
        calls = {"n": 0}

        def fake_get(url, headers=None, timeout=None):
            calls["n"] += 1
            return _FakeResponse({"status": "Ready_for_query"})

        data = wait_until_ready(_config(), get=fake_get, sleep=lambda _s: None)
        assert data["status"] == "Ready_for_query"
        assert calls["n"] == 1

    def test_polls_until_ready(self):
        calls = {"n": 0}

        def fake_get(url, headers=None, timeout=None):
            calls["n"] += 1
            status = "Ready_for_query" if calls["n"] >= 3 else "Building"
            return _FakeResponse({"status": status})

        sleeps: list[float] = []
        wait_until_ready(_config(), poll_interval_s=1, get=fake_get, sleep=sleeps.append)
        assert calls["n"] == 3
        assert sleeps == [1, 1]

    def test_raises_on_timeout_rather_than_returning_falsy(self):
        def fake_get(url, headers=None, timeout=None):
            return _FakeResponse({"status": "Building"})

        # timeout_s <= 0 means the very first not-ready check hits the deadline.
        with pytest.raises(VectorNotReadyError):
            wait_until_ready(_config(), timeout_s=0, get=fake_get, sleep=lambda _s: None)



class TestTigerGraph42StatusShape:
    def test_empty_rebuild_list_is_ready(self):
        class Conn:
            def getVectorIndexStatus(self):
                return {"NeedRebuildServers": []}

        ready, data = check_vector_status(_config(), conn=Conn())
        assert ready is True and data == {"NeedRebuildServers": []}

    def test_servers_still_rebuilding_is_not_ready(self):
        class Conn:
            def getVectorIndexStatus(self):
                return {"NeedRebuildServers": ["m1"]}

        assert check_vector_status(_config(), conn=Conn())[0] is False

    def test_wait_uses_the_authenticated_connection(self):
        calls = []

        class Conn:
            def getVectorIndexStatus(self):
                calls.append(1)
                return {"NeedRebuildServers": []}

        def no_http(*_a, **_k):
            raise AssertionError("must not make an unauthenticated HTTP call")

        wait_until_ready(_config(), get=no_http, sleep=lambda _s: None, conn=Conn())
        assert calls == [1]
