"""POST /r2/ask and GET /r2/status with a scripted model over the in-process corpus graph."""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.common.trials import TrialLog
from ogr.r2.local_graph import LocalR2Graph
from tests.r2.conftest import mini_corpus, mini_model  # noqa: F401  (fixtures)
from tests.r2.test_agent_core import FakeModel, call, finish, msg


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api_main, "OUT_DIR", tmp_path)
    return TestClient(api_main.app)


def _patch(monkeypatch, mini_model, script):  # noqa: F811
    monkeypatch.setattr(api_main.r2_run, "make_model", lambda config: FakeModel(script))
    monkeypatch.setattr(api_main.r2_run, "make_graph", lambda backend, corpus, config: LocalR2Graph(mini_model))


def test_ask_returns_record_and_history(client, monkeypatch, mini_model, tmp_path):  # noqa: F811
    _patch(monkeypatch, mini_model, [
        msg(call("find_events", sport="Athletics", event_contains="800 metres")),
        msg(finish(answer="Ann Alpha", citations=["E1", "NOPE"]), usage=(50, 5)),
    ])
    r = client.post("/r2/ask", json={"question": "Who won?", "backend": "local"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "answered" and body["answer"] == "Ann Alpha"
    assert body["graph_backend"] == "local" and body["citations"] == ["E1"]
    assert body["trace"] and body["input_tokens"] == 150
    entries = TrialLog(tmp_path / "history.jsonl").read("query")
    assert entries[0]["subject"] == "Who won?" and entries[0]["status"] == "done"


def test_blank_question_rejected(client):
    assert client.post("/r2/ask", json={"question": "  "}).status_code == 422


def test_model_not_configured_is_503(client, monkeypatch):
    def boom(config):
        raise RuntimeError("LLM_API_KEY is not set")

    monkeypatch.setattr(api_main.r2_run, "make_model", boom)
    r = client.post("/r2/ask", json={"question": "q"})
    assert r.status_code == 503 and "not configured" in r.json()["detail"]


def test_graph_unreachable_is_503(client, monkeypatch, mini_model):  # noqa: F811
    monkeypatch.setattr(api_main.r2_run, "make_model", lambda config: FakeModel([]))

    def boom(backend, corpus, config):
        raise ConnectionError("cannot reach TigerGraph")

    monkeypatch.setattr(api_main.r2_run, "make_graph", boom)
    r = client.post("/r2/ask", json={"question": "q"})
    assert r.status_code == 503 and "TigerGraph" in r.json()["detail"]


def test_agent_failure_is_error_not_answer(client, monkeypatch, mini_model, tmp_path):  # noqa: F811
    _patch(monkeypatch, mini_model, [ValueError("bad payload")])
    r = client.post("/r2/ask", json={"question": "q", "backend": "local"})
    assert r.status_code == 500 and "bad payload" in r.json()["detail"]
    assert "status" not in r.json()
    assert TrialLog(tmp_path / "history.jsonl").read("query")[0]["status"] == "error"


def test_status(client, monkeypatch):
    import ogr.graph.schema as schema

    monkeypatch.setattr(schema, "has_r2_answer_schema", lambda c: True)
    monkeypatch.setattr(api_main, "_get_client", lambda config: object())
    body = client.get("/r2/status").json()
    assert body["schema_installed"] is True and body["model"]
