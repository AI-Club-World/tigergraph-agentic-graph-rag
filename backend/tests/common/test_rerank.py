"""Tests for the P3 cross-encoder reranker (LLM-ALLOCATION plan G-2)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ogr.common import rerank as rerank_module
from ogr.common.config import RunConfig
from ogr.common.rerank import rerank
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker

import pytest

# Query embedding is strict (never hash noise): a stand-in model serves it here.
pytestmark = pytest.mark.usefixtures("fake_embedder")

CHUNKS = [{"chunk_id": "c0", "text": "zero"}, {"chunk_id": "c1", "text": "one"}, {"chunk_id": "c2", "text": "two"}]


def _creds(monkeypatch, on=True):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct" if on else "")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "tok" if on else "")


def test_orders_by_cross_encoder_score(monkeypatch):
    _creds(monkeypatch)
    sent = {}

    def fake_post(url, payload, token, timeout_s=60.0):
        sent.update(url=url, payload=payload)
        return {"result": {"response": [{"id": 0, "score": 0.1}, {"id": 2, "score": 0.9}, {"id": 1, "score": 0.5}]}}

    monkeypatch.setattr(rerank_module, "_post_json", fake_post)
    assert [c["chunk_id"] for c in rerank("q", CHUNKS)] == ["c2", "c1", "c0"]
    assert sent["url"].endswith("/ai/run/@cf/baai/bge-reranker-base")
    assert sent["payload"] == {"query": "q", "contexts": [{"text": "zero"}, {"text": "one"}, {"text": "two"}]}


def test_api_failure_keeps_retrieval_order(monkeypatch):
    _creds(monkeypatch)

    def fail(*_a, **_k):
        raise OSError("down")

    monkeypatch.setattr(rerank_module, "_post_json", fail)
    assert rerank("q", CHUNKS) == CHUNKS


def test_no_credentials_makes_no_call(monkeypatch):
    _creds(monkeypatch, on=False)
    monkeypatch.setattr(rerank_module, "_post_json", MagicMock(side_effect=AssertionError("called")))
    assert rerank("q", CHUNKS) == CHUNKS


def test_p3_context_reranks_fallback_prose(monkeypatch):
    """Fallback prose is reordered by the reranker before the [:20] cut."""
    import ogr.common.rerank as module
    from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic

    monkeypatch.setattr(module, "rerank", lambda _q, chunks: sorted(chunks, key=lambda c: c["text"], reverse=True))
    prompts = []

    def invoke(messages):
        prompts.append(messages[-1].content if isinstance(messages, list) else str(messages))
        resp = MagicMock()
        resp.tool_calls = []
        resp.usage_metadata = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
        resp.response_metadata = {}
        resp.content = (
            json.dumps({"operation": "TRAVERSE", "anchor": {}})
            if len(prompts) == 1 else json.dumps({"answer": "a", "explanation": "e"})
        )
        return resp

    model = MagicMock()
    model.invoke.side_effect = invoke
    client = TigerGraphClient(config=RunConfig(), mock_chunks=[
        {"chunk_id": "first_by_vector", "doc_id": "Q1", "text": "alpha"},
        {"chunk_id": "second_by_vector", "doc_id": "Q2", "text": "beta"},
    ])
    run_p3_agentic(
        "What came next?", llm_model=model, tg_client=client,
        entity_linker=EntityLinker(), config=RunConfig(llm_supports_tool_calling="false"),
    )
    context = prompts[-1]
    assert "[1] [Source: Q2]" in context  # "beta" outranks "alpha" despite vector order
