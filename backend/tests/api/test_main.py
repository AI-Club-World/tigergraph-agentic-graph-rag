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

    api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="test-key")
    api_main._queries.clear()
    api_main._builds.clear()
    with TestClient(api_main.app) as c:
        yield c
    api_main.app.dependency_overrides.clear()


HEADERS = {"X-API-Key": "test-key"}


class TestHealth:
    def test_health_needs_no_api_key(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestAuth:
    def test_missing_key_is_rejected(self, client):
        response = client.post("/query", json={"query": "q"})
        assert response.status_code == 401

    def test_wrong_key_is_rejected(self, client):
        response = client.post("/query", json={"query": "q"}, headers={"X-API-Key": "wrong"})
        assert response.status_code == 401

    def test_unconfigured_key_refuses_rather_than_running_open(self, client):
        api_main.app.dependency_overrides[get_config] = lambda: RunConfig(ogr_api_key="")
        response = client.post("/query", json={"query": "q"}, headers=HEADERS)
        assert response.status_code == 503

    def test_correct_key_is_accepted(self, client):
        response = client.post("/query", json={"query": "q"}, headers=HEADERS)
        assert response.status_code == 202


class TestQueryLifecycle:
    def test_post_query_returns_id_and_stream_token_immediately(self, client):
        response = client.post("/query", json={"query": "How many?"}, headers=HEADERS)
        assert response.status_code == 202
        body = response.json()
        assert "query_id" in body and "stream_token" in body

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
            "GET", f"/query/{body['query_id']}/stream", params={"token": body["stream_token"]}
        ) as response:
            assert response.status_code == 200
            events = [line for line in response.iter_lines() if line.startswith("event:")]

        assert "event: trace" in events
        assert events.count("event: pipeline") == 3
        assert events[-1] == "event: done"

    def test_stream_token_is_single_use(self, client):
        post = client.post("/query", json={"query": "q"}, headers=HEADERS)
        body = post.json()
        with client.stream(
            "GET", f"/query/{body['query_id']}/stream", params={"token": body["stream_token"]}
        ):
            pass
        second = client.get(
            f"/query/{body['query_id']}/stream", params={"token": body["stream_token"]}
        )
        assert second.status_code == 401

    def test_result_is_populated_once_the_stream_is_drained(self, client):
        post = client.post("/query", json={"query": "How many?"}, headers=HEADERS)
        body = post.json()
        with client.stream(
            "GET", f"/query/{body['query_id']}/stream", params={"token": body["stream_token"]}
        ) as response:
            for _ in response.iter_lines():
                pass

        result = client.get(f"/query/{body['query_id']}/result", headers=HEADERS)
        assert result.status_code == 200
        record = result.json()
        assert set(record["pipelines"]) == {"rag", "graphrag", "agentic_graphrag"}


class TestBuildStream:
    def test_build_reports_missing_corpus_honestly(self, client, monkeypatch, tmp_path):
        monkeypatch.setattr(api_main, "CORPUS_PATH", tmp_path / "absent.jsonl")
        post = client.post("/build", headers=HEADERS)
        body = post.json()

        with client.stream(
            "GET", f"/build/{body['build_id']}/stream", params={"token": body["stream_token"]}
        ) as response:
            lines = list(response.iter_lines())

        assert any(line == "event: build" for line in lines)
        error_payloads = [
            json.loads(lines[i + 1][len("data: "):])
            for i, line in enumerate(lines)
            if line == "event: build"
        ]
        assert any(p["status"] == "error" for p in error_payloads)


    def test_no_pipeline_is_ready_without_tigergraph(self, client, monkeypatch, tmp_path):
        """Every pipeline queries TigerGraph, so a build that cannot reach it
        stops at schema_install and marks nothing ready (it used to mark RAG
        ready right after local chunk+embed)."""
        corpus = tmp_path / "corpus.jsonl"
        corpus.write_text(
            json.dumps({"doc_id": "Q1", "title": "Sailing at the 2016 Summer Olympics", "text": "Sailing text."})
            + "\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(api_main, "CORPUS_PATH", corpus)

        class _Offline:
            conn = None

            def _ensure_connection(self):
                return None

        monkeypatch.setattr(api_main, "_get_client", lambda config: _Offline())
        body = client.post("/build", headers=HEADERS).json()
        with client.stream(
            "GET", f"/build/{body['build_id']}/stream", params={"token": body["stream_token"]}
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
    def test_stream_token_ttl_comes_from_config(self):
        from ogr.common.config import get_default_config

        assert api_main._stream_tokens.ttl_s == get_default_config().ogr_stream_token_ttl_s

    def test_finished_queries_are_evicted_beyond_the_cap(self, client):
        for i in range(api_main._MAX_RETAINED + 20):
            api_main._queries[f"old-{i}"] = {"queue": None, "record": None}
        client.post("/query", json={"query": "q"}, headers=HEADERS)
        assert len(api_main._queries) <= api_main._MAX_RETAINED + 1
        assert "old-0" not in api_main._queries
