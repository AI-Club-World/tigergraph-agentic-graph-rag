"""API hardening: no credential leaks, no partial settings writes, reserved
run ids, safe imports and uploads, one build or run at a time."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.api.security import get_config
from ogr.common.config import RunConfig

HEADERS = {"X-API-Key": "k"}
DOC = json.dumps({"doc_id": "Q1", "title": "Sailing at the 2016 Summer Olympics", "text": "Sailing."})


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api_main, "CORPUS_DIR", tmp_path / "corpus")
    api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="k")
    api_main._builds.clear()
    api_main._batch_tasks.clear()
    api_main._runtime_overrides.clear()
    with TestClient(api_main.app) as c:
        yield c
    api_main.app.dependency_overrides.clear()
    api_main._builds.clear()
    api_main._batch_tasks.clear()
    api_main._runtime_overrides.clear()


class _Running:
    def done(self):
        return False

    def cancelled(self):
        return False


def test_settings_never_expose_url_credentials(client):
    api_main._runtime_overrides["llm_base_url"] = "http://admin:s3cret@10.0.0.5:8080/v1"
    body = client.get("/settings").json()
    assert body["llm_base_host"] == "10.0.0.5:8080" and "s3cret" not in json.dumps(body)


def test_health_detail_hides_hosts_and_checks_are_cached(client, monkeypatch):
    import ogr.verify as verify

    calls = []

    def check(config, _client=None):
        calls.append(1)
        return "OK", f"connected to {config.tg_host} as https://u:pw@db.internal"

    monkeypatch.setattr(verify, "check_tigergraph", check)
    api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="k", tg_host="https://tg.secret.io")
    first = client.get("/health/db").json()
    assert "tg.secret.io" not in first["detail"] and "pw@" not in first["detail"]
    client.get("/health/db")
    assert len(calls) == 1, "a second poll within the cache window does not re-run the check"


def test_a_refused_settings_change_changes_nothing(client):
    before = client.get("/settings").json()
    response = client.patch(
        "/settings", headers=HEADERS, json={"llm_model": "other-model", "embedding_model": "qwen3-embedding-0.6b"}
    )
    assert response.status_code == 409
    assert client.get("/settings").json()["llm_model"] == before["llm_model"]


@pytest.mark.parametrize("run_id", ["history", "datasets", "embeddings", "chunks"])
def test_state_file_names_are_not_run_ids(client, run_id):
    record = {"record": {"query_id": "q", "query_text": "q", "pipelines": {}}}
    response = client.post("/runs/import", headers=HEADERS, json={"run_id": run_id, "records": [record]})
    assert response.status_code == 400


def test_a_malformed_import_is_refused_and_leaves_history_working(client):
    response = client.post("/runs/import", headers=HEADERS, json=[{"record": {}}])
    assert response.status_code == 400
    assert not list(api_main.OUT_DIR.glob("*.jsonl")) if api_main.OUT_DIR.exists() else True
    assert client.get("/runs", headers=HEADERS).status_code == 200


def test_one_broken_run_file_does_not_break_the_list(client):
    api_main.OUT_DIR.mkdir(parents=True, exist_ok=True)
    (api_main.OUT_DIR / "broken.jsonl").write_text(
        json.dumps({"run_config": {}}) + "\n" + json.dumps({"record": {}}) + "\n"
    )
    assert client.get("/runs", headers=HEADERS).status_code == 200


def test_upload_refuses_non_utf8_and_oversize(client, monkeypatch):
    bad = client.post("/corpora/latin", headers=HEADERS, content='{"doc_id": "Q1", "text": "caf\xe9"}\n'.encode("latin-1"))
    assert bad.status_code == 400 and "UTF-8" in bad.json()["detail"]
    monkeypatch.setattr(api_main, "MAX_UPLOAD_BYTES", 10)
    big = client.post("/corpora/big", headers=HEADERS, content=(DOC + "\n").encode())
    assert big.status_code == 413
    assert not list((api_main.CORPUS_DIR).glob("*")), "nothing is left behind"


def test_upload_is_exclusive_unless_overwriting(client):
    assert client.post("/corpora/a", headers=HEADERS, content=DOC.encode()).status_code == 201
    assert client.post("/corpora/a", headers=HEADERS, content=DOC.encode()).status_code == 409
    assert client.post("/corpora/a?overwrite=true", headers=HEADERS, content=DOC.encode()).status_code == 201


def test_a_long_description_is_kept(client):
    client.post("/corpora/a", headers=HEADERS, content=DOC.encode())
    text = "word " * 60
    body = client.patch("/corpora/a", headers=HEADERS, json={"description": text}).json()
    assert body["description"] == text.strip()


def test_no_build_or_switch_while_a_benchmark_runs(client):
    client.post("/corpora/a", headers=HEADERS, content=DOC.encode())
    api_main._batch_tasks["run-1"] = _Running()
    build = client.post("/build", headers=HEADERS, json={"dataset": "a"})
    assert build.status_code == 409 and build.json()["detail"]["code"] == "batch_running"
    switch = client.post("/embeddings/switch", headers=HEADERS, json={"model": "qwen3-embedding-0.6b"})
    assert switch.status_code == 409 and switch.json()["detail"]["code"] == "batch_running"


def test_a_second_build_request_during_the_first_ones_checks_is_refused(client, monkeypatch):
    """The first request awaits a graph probe; a second arriving meanwhile must see the slot taken."""
    client.post("/corpora/a", headers=HEADERS, content=DOC.encode())
    gate = {"second": None}

    def probe(_client):
        # While the first request is inside its check, the second one runs.
        gate["second"] = client.post("/build", headers=HEADERS, json={"dataset": "a"})
        return False

    monkeypatch.setattr(api_main, "_graph_has_documents", probe)
    monkeypatch.setattr(api_main, "_run_build", lambda *a, **k: asyncio.sleep(0))
    first = client.post("/build", headers=HEADERS, json={"dataset": "a"})
    assert first.status_code == 202
    assert gate["second"].status_code == 409 and gate["second"].json()["detail"]["code"] == "build_running"
