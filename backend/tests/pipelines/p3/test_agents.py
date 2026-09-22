"""Tests for Group 3: Tool agents (one conformance test per agent).

Verification Plan Group 3:
- One conformance test per agent returning AgentResult
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from ogr.graph.client import TigerGraphClient
from ogr.common.config import RunConfig
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
from ogr.pipelines.p3_agentic.intent import Anchor, AnchorConstraint, IntentSchema


def _make_client(mock_query_results=None, mock_chunks=None):
    client = TigerGraphClient(config=RunConfig(), mock_chunks=mock_chunks or [])
    if mock_query_results is not None:
        client._run_query = MagicMock(return_value=mock_query_results)
    return client


def _make_anchors(**kwargs) -> ResolvedAnchors:
    return ResolvedAnchors(**kwargs)


class TestGraphTraversalConformance:
    def test_returns_agent_result(self):
        from ogr.pipelines.p3_agentic.agents.graph_traversal import run_graph_traversal
        client = _make_client(mock_query_results=[
            {"v_id": "Q123_event", "attributes": {"event_id": "Q123", "event_name": "Previous Event", "doc_id": "Q200"}}
        ])
        anchors = _make_anchors(title="Triathlon at 2016 Olympics")
        result = run_graph_traversal(client, anchors, edge_type="PREV_EDITION", hops=1)
        assert isinstance(result, AgentResult)
        assert isinstance(result.chunks_returned, int)
        assert isinstance(result.citations_count, int)
        assert isinstance(result.latency_ms, float)
        assert result.latency_ms >= 0.0

    def test_empty_anchor_returns_error_result(self):
        from ogr.pipelines.p3_agentic.agents.graph_traversal import run_graph_traversal
        client = _make_client(mock_query_results=[])
        anchors = _make_anchors()  # no title, no event_id, no venue
        result = run_graph_traversal(client, anchors)
        assert result.error is not None


class TestSimilaritySearchConformance:
    def test_returns_agent_result(self):
        from ogr.pipelines.p3_agentic.agents.similarity_search import run_similarity_search
        mock_chunks = [
            {"chunk_id": "Q1_c0", "doc_id": "Q1", "text": "Some text", "score": 0.9, "vtype": "Chunk"},
        ]
        client = TigerGraphClient(config=RunConfig(), mock_chunks=mock_chunks)
        result = run_similarity_search(
            client,
            query="Test query",
            k=5,
            triggered_by="scope_coverage_fail",
        )
        assert isinstance(result, AgentResult)
        assert result.strategy_change is True  # always a strategy deviation
        assert result.chunks_returned >= 0
        assert isinstance(result.latency_ms, float)

    def test_strategy_change_always_true(self):
        from ogr.pipelines.p3_agentic.agents.similarity_search import run_similarity_search
        client = TigerGraphClient(config=RunConfig(), mock_chunks=[])
        result = run_similarity_search(client, query="test", k=5)
        assert result.strategy_change is True


class TestDocumentRetrievalConformance:
    def test_returns_agent_result(self):
        from ogr.pipelines.p3_agentic.agents.document_retrieval import run_document_retrieval
        mock_chunks = [
            {"chunk_id": "Q500_c0", "doc_id": "Q500", "text": "Prose text", "vtype": "Chunk"},
        ]
        client = TigerGraphClient(config=RunConfig(), mock_chunks=mock_chunks)
        result = run_document_retrieval(client, doc_ids=["Q500"], triggered_by="groundedness_fail")
        assert isinstance(result, AgentResult)
        assert result.strategy_change is True  # prose fallback is always a deviation
        assert isinstance(result.chunks_returned, int)

    def test_no_doc_ids_returns_error(self):
        from ogr.pipelines.p3_agentic.agents.document_retrieval import run_document_retrieval
        client = TigerGraphClient(config=RunConfig(), mock_chunks=[])
        result = run_document_retrieval(client, doc_ids=None)
        assert result.error is not None


class TestAggregationConformance:
    def test_count_returns_agent_result(self):
        from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
        client = _make_client(mock_query_results=[
            {"attributes": {"count": 26, "doc_id": "Q100"}}
        ])
        intent = IntentSchema(
            operation="COUNT",
            anchor=Anchor(sport="Sailing", games="2016-Summer"),
            target_field="nations",
        )
        anchors = _make_anchors(sport="Sailing", games="2016-Summer")
        result = run_aggregation(client, intent, anchors)
        assert isinstance(result, AgentResult)
        assert isinstance(result.chunks_returned, int)
        assert isinstance(result.latency_ms, float)

    def test_argmax_returns_agent_result(self):
        from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
        client = _make_client(mock_query_results=[
            {"v_id": "Q200", "attributes": {"event_id": "Q200", "event_name": "Top Event", "win_value": "USA"}}
        ])
        intent = IntentSchema(
            operation="ARGMAX",
            anchor=Anchor(sport="Swimming", games="2008-Summer"),
            target_field="gold_noc",
        )
        anchors = _make_anchors(sport="Swimming", games="2008-Summer")
        result = run_aggregation(client, intent, anchors)
        assert isinstance(result, AgentResult)

    def test_invalid_operation_returns_error(self):
        from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
        client = _make_client(mock_query_results=[])
        intent = IntentSchema(operation="LOOKUP")
        anchors = _make_anchors()
        result = run_aggregation(client, intent, anchors)
        assert result.error is not None


class TestMultiHopConformance:
    def test_returns_agent_result(self):
        from ogr.pipelines.p3_agentic.agents.multi_hop import run_multi_hop
        client = _make_client(mock_query_results=[])
        intent = IntentSchema(
            operation="TRAVERSE",
            anchor=Anchor(title="Triathlon at the 2016 Summer Olympics"),
            target_field="sport_name",
        )
        anchors = _make_anchors(title="Triathlon at the 2016 Summer Olympics")
        result = run_multi_hop(client, intent, anchors)
        assert isinstance(result, AgentResult)
        assert isinstance(result.chunks_returned, int)
        assert isinstance(result.latency_ms, float)

    def test_empty_anchor_returns_error(self):
        from ogr.pipelines.p3_agentic.agents.multi_hop import run_multi_hop
        client = _make_client(mock_query_results=[])
        intent = IntentSchema(operation="TRAVERSE")
        anchors = _make_anchors()
        result = run_multi_hop(client, intent, anchors)
        assert result.error is not None
