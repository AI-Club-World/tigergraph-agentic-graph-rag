"""Tests for API-01 — the FastAPI service.

Pipelines are monkeypatched to stub callables (same idea as
test_dispatcher.py); no live LLM or TigerGraph is used. This proves the
HTTP/SSE/auth layer works, not that a real pipeline answers correctly —
that is what the pipeline test suites are for.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import ogr.api.main as api_main
from ogr.api.security import get_config
from ogr.common.config import RunConfig
from ogr.common.contracts import Citation, PipelineRecord, TokenUsage, TraceStep


def _record(pipeline: str, answer: str = "26") -> PipelineRecord:
    return PipelineRecord(
        pipeline=pipeline,  # type: ignore[arg-type]
        answer=answer,
        explanation="e",
        citations=[Citation(source_id="Q1", chunk_id=None, ref_type="chunk")],
        chunks_returned=1,
        citations_count=1,
        tokens=TokenUsage(input=90, output=10, total=100),
    )


# Queries and runs start only once the active model's embeddings are complete.
pytestmark = pytest.mark.usefixtures("ready_embeddings")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(api_main, "run_p1_rag", lambda query, client, config: _record("rag"))
    monkeypatch.setattr(
        api_main, "run_p2_graphrag", lambda query, client, config: _record("graphrag")
    )

    async def fake_astream_p3(query, tg_client=None, config=None):
        yield TraceStep(step_n=1, agent_type="entity_linking", tool_called="Q1")
        yield _record("agentic_graphrag")

    monkeypatch.setattr(api_main, "astream_p3_agentic", fake_astream_p3)

    api_main.app.dependency_overrides[get_config] = lambda: RunConfig()
    api_main._queries.clear()
    api_main._builds.clear()
    with TestClient(api_main.app) as c:
        yield c
    api_main.app.dependency_overrides.clear()


HEADERS: dict[str, str] = {}  # the API is open: no key


class TestHealth:
    def test_health_needs_no_api_key(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestOpenAccess:
    """The application is open: no key, session or stream token anywhere."""

    def test_a_query_needs_no_key(self, client):
        assert client.post("/query", json={"query": "q"}).status_code == 202

    def test_the_sign_in_routes_are_gone(self, client):
        assert client.post("/auth/session", json={"key": "x"}).status_code in (404, 405)


class TestQueryLifecycle:
    def test_post_query_returns_its_id_immediately(self, client):
        response = client.post("/query", json={"query": "How many?"}, headers=HEADERS)
        assert response.status_code == 202
        assert set(response.json()) == {"query_id"}

    def test_result_is_409_before_the_stream_completes(self, client):
        # Bypass the async task entirely: register a query with no record yet.
        api_main._queries["pending-id"] = {"queue": None, "record": None}
        response = client.get("/query/pending-id/result", headers=HEADERS)
        assert response.status_code == 409

    def test_unknown_query_id_is_404(self, client):
        response = client.get("/query/does-not-exist/result", headers=HEADERS)
        assert response.status_code == 404

    def test_stream_delivers_trace_pipeline_and_done_events(self, client):
        post = client.post("/query", json={"query": "How many?"}, headers=HEADERS)
        body = post.json()

        with client.stream(
            "GET", f"/query/{body['query_id']}/stream"
        ) as response:
            assert response.status_code == 200
            events = [line for line in response.iter_lines() if line.startswith("event:")]

        assert "event: trace" in events
        assert events.count("event: pipeline") == 3
        assert events[-1] == "event: done"

    def test_result_is_populated_once_the_stream_is_drained(self, client):
        post = client.post("/query", json={"query": "How many?"}, headers=HEADERS)
        body = post.json()
        with client.stream(
            "GET", f"/query/{body['query_id']}/stream"
        ) as response:
            for _ in response.iter_lines():
                pass

        result = client.get(f"/query/{body['query_id']}/result", headers=HEADERS)
        assert result.status_code == 200
        record = result.json()
        assert set(record["pipelines"]) == {"rag", "graphrag", "agentic_graphrag"}


class TestBuildStream:
    def test_unknown_dataset_is_refused_before_a_build_starts(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(api_main, "CORPUS_DIR", tmp_path)
        response = client.post("/build", headers=HEADERS, json={"dataset": "absent"})
        assert response.status_code == 404
        assert "absent" in response.json()["detail"]

    def test_no_pipeline_is_ready_without_tigergraph(self, client, monkeypatch, tmp_path, fake_embedder):
        """Every pipeline queries TigerGraph, so a build that cannot reach it
        stops at schema_install and marks nothing ready (it used to mark RAG
        ready right after local chunk+embed)."""
        corpus = tmp_path / "corpus.jsonl"
        monkeypatch.setattr(api_main, "OUT_DIR", tmp_path / "fresh-out")  # nothing built yet
        corpus.write_text(
            json.dumps({"doc_id": "Q1", "title": "Sailing at the 2016 Summer Olympics", "text": "Sailing text."})
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(api_main, "CORPUS_DIR", tmp_path)

        class _Offline:
            conn = None

            def _ensure_connection(self):
                return None

        monkeypatch.setattr(api_main, "_get_client", lambda config: _Offline())
        body = client.post("/build", headers=HEADERS).json()
        with client.stream(
            "GET", f"/build/{body['build_id']}/stream"
        ) as response:
            lines = list(response.iter_lines())
        events = [json.loads(lines[i + 1][len("data: "):]) for i, line in enumerate(lines) if line == "event: build"]

        stages = [e["stage"] for e in events if e["status"] == "done"]
        assert stages == ["parse_infoboxes", "chunk_documents", "embed_chunks"]
        assert events[-1]["stage"] == "schema_install" and events[-1]["status"] == "error"
        assert not any(e["status"] == "ready" for e in events)
        elapsed = [e["elapsed_ms"] for e in events]
        assert elapsed == sorted(elapsed)  # measured from build start


class TestBatchRecords:
    def test_unknown_run_id_is_404(self, client):
        response = client.get("/batch/no-such-run/records", headers=HEADERS)
        assert response.status_code == 404

    def test_reads_records_skipping_the_run_config_header(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(api_main, "OUT_DIR", tmp_path)
        run_path = tmp_path / "run-a.jsonl"
        run_path.write_text(
            json.dumps({"run_config": {"llm_model": "gpt-4o-mini"}}) + "\n"
            + json.dumps({"question_id": "pub-001"}) + "\n",
            encoding="utf-8",
        )
        response = client.get("/batch/run-a/records", headers=HEADERS)
        assert response.status_code == 200
        records = response.json()
        assert len(records) == 1
        assert records[0]["question_id"] == "pub-001"


class TestStateHardening:
    def test_finished_queries_are_evicted_beyond_the_cap(self, client):
        for i in range(api_main._MAX_RETAINED + 20):
            api_main._queries[f"old-{i}"] = {"queue": None, "record": None}
        client.post("/query", json={"query": "q"}, headers=HEADERS)
        assert len(api_main._queries) <= api_main._MAX_RETAINED + 1
        assert "old-0" not in api_main._queries
