"""DP-3: a rate-limited LLM stops the run — never folded into an answer record."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ogr.common import llm
from ogr.common.config import RunConfig
from ogr.common.llm import LLMRateLimitError
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p1_rag import run_p1_rag
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic


# Query embedding is strict (never hash noise): a stand-in model serves it here.
pytestmark = pytest.mark.usefixtures("fake_embedder")


class _TooManyRequests(Exception):
    status_code = 429


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def _limited_model(monkeypatch):
    model = MagicMock()
    model.invoke.side_effect = _TooManyRequests("429 Too Many Requests")
    monkeypatch.setitem(llm._MODEL_LABELS, id(model), "nvidia_nim/meta/llama-3.3-70b-instruct")
    return model


def test_p1_propagates_rate_limit(monkeypatch):
    client = TigerGraphClient(config=RunConfig(), mock_chunks=[])
    with pytest.raises(LLMRateLimitError, match="nvidia_nim"):
        run_p1_rag("q", client=client, config=RunConfig(), model=_limited_model(monkeypatch))


def test_p3_propagates_rate_limit(monkeypatch):
    with pytest.raises(LLMRateLimitError, match="nvidia_nim"):
        run_p3_agentic(
            "q", llm_model=_limited_model(monkeypatch), tg_client=TigerGraphClient(config=RunConfig(), mock_chunks=[]),
            entity_linker=EntityLinker(), config=RunConfig(llm_supports_tool_calling="false"),
        )
