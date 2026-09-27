"""Every query and build attempt is captured in the trial history."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.api.security import get_config
from ogr.common.config import RunConfig
from ogr.common.contracts import PipelineRecord, TokenUsage
from ogr.common.trials import TrialLog

HEADERS = {"X-API-Key": "k"}


def _record(pipeline: str, status: str = "done") -> PipelineRecord:
    return PipelineRecord(
        pipeline=pipeline, answer="26", explanation="e", citations=[], chunks_returned=0,
        citations_count=0, tokens=TokenUsage(input=9, output=1, total=10), status=status,
        error_detail="boom" if status == "error" else None,
    )


# Queries and runs start only once the active model's embeddings are complete.
pytestmark = pytest.mark.usefixtures("ready_embeddings")


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(api_main, "run_p1_rag", lambda query, client, config: _record("rag"))
    monkeypatch.setattr(api_main, "run_p2_graphrag", lambda query, client, config: _record("graphrag", "error"))

    async def p3(query, tg_client=None, config=None):
        yield _record("agentic_graphrag")

    monkeypatch.setattr(api_main, "astream_p3_agentic", p3)
    monkeypatch.setattr(api_main, "CORPUS_DIR", tmp_path)
    previous = api_main.app.dependency_overrides.get(get_config)
    api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="k", llm_model="m1")
    with TestClient(api_main.app) as c:
        yield c
    if previous is None:
        api_main.app.dependency_overrides.pop(get_config, None)
    else:
        api_main.app.dependency_overrides[get_config] = previous


def test_query_is_captured_with_per_pipeline_outcome(client):
    body = client.post("/query", headers=HEADERS, json={"query": "How many?"}).json()
    with client.stream("GET", f"/query/{body['query_id']}/stream", params={"token": body["stream_token"]}) as r:
        list(r.iter_lines())
    [trial] = client.get("/history", headers=HEADERS, params={"kind": "query"}).json()
    assert trial["subject"] == "How many?" and trial["status"] == "partial"
    assert trial["pipelines"]["graphrag"]["error"] == "boom" and trial["tokens"] == 30
    assert trial["llm_model"] == "m1"


def test_refused_build_is_captured(client):
    assert client.post("/build", headers=HEADERS, json={"dataset": "nope"}).status_code == 404
    [trial] = client.get("/history", headers=HEADERS, params={"kind": "build"}).json()
    assert trial["status"] == "refused" and trial["dataset"] == "nope" and "Unknown dataset" in trial["error"]


def test_history_is_newest_first_and_filterable(tmp_path):
    log = TrialLog(tmp_path / "h.jsonl")
    log.append("query", "done", subject="a")
    log.append("build", "ready", subject="b")
    (tmp_path / "h.jsonl").open("a").write("not json\n")
    assert [e["subject"] for e in log.read()] == ["b", "a"]
    assert [e["subject"] for e in log.read("query")] == ["a"]
    assert json.loads((tmp_path / "h.jsonl").read_text().splitlines()[0])["kind"] == "query"
