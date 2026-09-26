"""/health/status: each dependency judged on its own (indicator fixes)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
import ogr.verify as verify
from ogr.api.security import get_config
from ogr.common.config import RunConfig


@pytest.fixture
def client(monkeypatch):
    previous = api_main.app.dependency_overrides.get(get_config)
    api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="k")
    with TestClient(api_main.app) as c:
        yield c
    if previous is None:
        api_main.app.dependency_overrides.pop(get_config, None)
    else:
        api_main.app.dependency_overrides[get_config] = previous


def test_slow_llm_does_not_mark_the_database_down(client, monkeypatch):
    monkeypatch.setattr(api_main, "HEALTH_CHECK_TIMEOUT_S", 0.2)
    monkeypatch.setattr(verify, "check_tigergraph", lambda config, c=None: ("OK", "up"))
    monkeypatch.setattr(verify, "check_llm", lambda config: time.sleep(1) or ("OK", "late"))
    monkeypatch.setattr(verify, "check_embedding", lambda config: ("SKIP", "local"))
    body = client.get("/health/status").json()
    assert body["db"]["status"] == "ok"
    assert body["llm"]["status"] == "fail" and "did not answer" in body["llm"]["detail"]
    assert body["embedding"]["status"] == "skip"


def test_tigergraph_check_uses_rest_echo_not_version():
    conn = MagicMock()
    conn.echo.return_value = "Hello GSQL"
    conn.getVersion.side_effect = AssertionError("/version may be refused to a query token")
    tg = MagicMock(conn=conn)
    status, detail = verify.check_tigergraph(RunConfig(tg_host="https://ws.example"), tg)
    assert status == "OK" and "Hello GSQL" in detail


def test_embedding_ok_when_cloudflare_answers(monkeypatch):
    from ogr.common import embeddings

    monkeypatch.setattr(embeddings, "_embed_cloudflare", lambda texts, a, t: [[0.1] * 1024])
    status, detail = verify.check_embedding(
        RunConfig(cloudflare_account_id="a", cloudflare_api_token="t")
    )
    assert status == "OK" and "1024-dim" in detail


def test_embedding_fails_with_no_tier(monkeypatch):
    from ogr.common import embeddings

    monkeypatch.setattr(embeddings, "_MODELS", {})
    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", lambda *a, **k: None)
    status, detail = verify.check_embedding(RunConfig(cloudflare_account_id="", cloudflare_api_token=""))
    assert status == "FAIL" and "hash noise" in detail
