"""Tests for the benchmark routes: GET /datasets, POST /batch, GET /runs,
POST /runs/import, GET /batch/{run_id}/records. Pipelines are stubbed; no
live LLM or TigerGraph is used."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.api.security import get_config
from ogr.common.config import RunConfig
from ogr.common.contracts import Citation, PipelineRecord, TokenUsage

HEADERS = {"X-API-Key": "test-key"}


def _record(pipeline: str) -> PipelineRecord:
    return PipelineRecord(
        pipeline=pipeline,  # type: ignore[arg-type]
        answer="26",
        explanation="e",
        citations=[Citation(source_id="Q1", chunk_id=None, ref_type="entity")],
        tokens=TokenUsage(input=90, output=10, total=100),
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    questions = tmp_path / "questions"
    questions.mkdir()
    (questions / "mini.jsonl").write_text(
        json.dumps({"qid": "q1", "question": "How many?", "qtype": "aggregation", "answer": ["26"], "gold_doc_ids": ["Q1"]})
        + "\n"
    )
    monkeypatch.setattr(api_main, "QUESTIONS_DIR", questions)
    monkeypatch.setattr(api_main, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(
        api_main,
        "default_pipelines",
        lambda config, client: {p: (lambda q, p=p: _record(p)) for p in ("rag", "graphrag", "agentic_graphrag")},
    )
    api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="test-key")
    api_main._batch_tasks.clear()
    with TestClient(api_main.app) as c:
        yield c
    api_main.app.dependency_overrides.clear()
    api_main._batch_tasks.clear()


def _wait_complete(client, run_id: str) -> dict:
    for _ in range(100):
        runs = {r["run_id"]: r for r in client.get("/runs", headers=HEADERS).json()}
        if run_id in runs and runs[run_id]["status"] != "running":
            return runs[run_id]
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never completed")


def test_routes_require_the_api_key(client):
    assert client.get("/runs").status_code == 401
    assert client.post("/runs/import", json=[]).status_code == 401
    assert client.post("/batch", json={"dataset": "mini"}).status_code == 401


def test_datasets_lists_question_files(client):
    assert client.get("/datasets", headers=HEADERS).json() == ["mini"]


def test_batch_execution_lands_in_history_with_metadata(client):
    response = client.post("/batch", json={"dataset": "mini", "run_id": "run-a"}, headers=HEADERS)
    assert response.status_code == 202
    assert response.json() == {"run_id": "run-a", "status": "running"}

    summary = _wait_complete(client, "run-a")
    assert summary["status"] == "complete"
    assert summary["dataset"] == "mini"
    assert summary["n_questions"] == 1
    assert summary["run_config"]["embedding_model"]
    assert summary["pipelines"]["agentic_graphrag"]["em"] == 1.0

    records = client.get("/batch/run-a/records", headers=HEADERS).json()
    assert records[0]["qid"] == "q1"
    assert records[0]["scores"]["rag"]["f1"] == 1.0


def test_batch_rejects_unknown_dataset_and_duplicate_run(client):
    assert client.post("/batch", json={"dataset": "../x"}, headers=HEADERS).status_code == 404
    client.post("/batch", json={"dataset": "mini", "run_id": "dup"}, headers=HEADERS)
    _wait_complete(client, "dup")
    assert client.post("/batch", json={"dataset": "mini", "run_id": "dup"}, headers=HEADERS).status_code == 409


def test_import_then_list(client):
    client.post("/batch", json={"dataset": "mini", "run_id": "src"}, headers=HEADERS)
    _wait_complete(client, "src")
    exported = client.get("/batch/src/records", headers=HEADERS).json()

    response = client.post(
        "/runs/import",
        json={"run_id": "copy", "run_config": {"llm_model": "old-model"}, "records": exported},
        headers=HEADERS,
    )
    assert response.status_code == 201
    assert response.json()["run_config"]["llm_model"] == "old-model"
    assert {r["run_id"] for r in client.get("/runs", headers=HEADERS).json()} == {"src", "copy"}

    assert client.post("/runs/import", json={"run_id": "copy", "records": exported}, headers=HEADERS).status_code == 409
    assert client.post("/runs/import", json={"records": []}, headers=HEADERS).status_code == 400


def test_unknown_run_records_is_404(client):
    assert client.get("/batch/nope/records", headers=HEADERS).status_code == 404


def test_timing_mode_is_recorded_in_the_run_header(client):
    response = client.post(
        "/batch", json={"dataset": "mini", "run_id": "run-t", "latency_mode": "timing"}, headers=HEADERS
    )
    assert response.status_code == 202
    summary = _wait_complete(client, "run-t")
    assert summary["run_config"]["latency_mode"] == "timing"
    assert summary["run_config"]["pool_size"] == 1


def test_unknown_latency_mode_is_rejected(client):
    response = client.post("/batch", json={"dataset": "mini", "latency_mode": "fast"}, headers=HEADERS)
    assert response.status_code == 422


def test_benchmark_run_is_captured_as_a_trial(client):
    run_id = client.post("/batch", headers=HEADERS, json={"dataset": "mini", "run_id": "trial-1"}).json()["run_id"]
    _wait_complete(client, run_id)
    for _ in range(100):
        trials = client.get("/history", headers=HEADERS, params={"kind": "benchmark"}).json()
        if trials:
            break
        time.sleep(0.02)
    [trial] = trials
    assert trial["status"] == "complete" and trial["run_id"] == "trial-1" and trial["dataset"] == "mini"
    assert trial["llm_model"] and "llm_api_key" not in trial
