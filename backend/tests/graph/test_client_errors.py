"""Graph query failures are reported, not read as "no evidence"."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p2_graphrag import run_p2_graphrag
from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic
from tests.pipelines.test_p2 import _linker, _model

pytestmark = pytest.mark.usefixtures("fake_embedder")

LOOKUP = {
    "operation": "LOOKUP",
    "anchor": {"title": "Sailing at the 2016 Summer Olympics"},
    "target_field": "nations",
    "constraints": [],
}


def _failing_client() -> TigerGraphClient:
    conn = MagicMock()
    conn.runInstalledQuery.side_effect = RuntimeError("connection reset")
    conn.getEdges.side_effect = RuntimeError("connection reset")
    return TigerGraphClient(config=RunConfig(), conn=conn)


def test_a_failed_query_returns_empty_and_is_recorded_once():
    client = _failing_client()
    assert client._run_query("q1_lookup", {}) == []
    assert client.drain_errors() == ["q1_lookup: connection reset"]
    assert client.drain_errors() == []


def test_p2_reports_the_failure_but_keeps_its_status():
    client = _failing_client()
    record = run_p2_graphrag(
        "How many nations competed?", client=client, config=RunConfig(),
        model=_model(LOOKUP), entity_linker=_linker(),
    )
    assert record.status == "done"
    assert record.error_detail == "graph query error: q1_lookup: connection reset"


def test_p3_puts_the_failure_on_the_trace_step_that_ran_it():
    client = _failing_client()
    record = run_p3_agentic(
        "How many nations competed?", llm_model=_model(LOOKUP), tg_client=client,
        entity_linker=_linker(), config=RunConfig(llm_supports_tool_calling="false"),
    )
    flagged = [s for s in record.trace if "graph query error" in s.notes]
    assert flagged and "q1_lookup: connection reset" in flagged[0].notes
    assert record.error_detail and record.error_detail.startswith("graph query error: q1_lookup")


class TestTransientReadRetry:
    """Savanna intermittently rejects a read with an empty-token error (REST-10016)."""

    @pytest.fixture(autouse=True)
    def no_wait(self, monkeypatch):
        import ogr.graph.client as client_module
        monkeypatch.setattr(client_module, "READ_BACKOFF_S", 0.0)

    def test_a_transient_failure_is_retried(self):
        conn = MagicMock()
        conn.runInstalledQuery.side_effect = [
            RuntimeError("Access Denied because the input token = '' is empty or too short, REST-10016"),
            [{"results": [{"event_id": "e1"}]}],
        ]
        client = TigerGraphClient(config=RunConfig(), conn=conn)
        assert client._run_query("q1_lookup", {}) == [{"event_id": "e1"}]
        assert client.drain_errors() == []

    def test_a_non_transient_failure_is_not_retried(self):
        conn = MagicMock()
        conn.runInstalledQuery.side_effect = RuntimeError("GSQL-7004 invalid vertex type")
        client = TigerGraphClient(config=RunConfig(), conn=conn)
        assert client._run_query("q1_lookup", {}) == []
        assert conn.runInstalledQuery.call_count == 1

    def test_a_vocabulary_that_cannot_load_raises_instead_of_reading_as_empty(self):
        from ogr.graph.client import GraphUnavailableError

        conn = MagicMock()
        conn.getVertices.side_effect = RuntimeError("REST-10016 Access Denied")
        client = TigerGraphClient(config=RunConfig(), conn=conn)
        with pytest.raises(GraphUnavailableError, match="Games"):
            client.get_vocabulary("Games")
        assert conn.getVertices.call_count == 3

    def test_p3_turns_it_into_an_error_record_so_a_batch_retries_the_question(self):
        conn = MagicMock()
        conn.getVertices.side_effect = RuntimeError("REST-10016 Access Denied")
        client = TigerGraphClient(config=RunConfig(), conn=conn)
        record = run_p3_agentic(
            "How many nations competed?", llm_model=_model(LOOKUP), tg_client=client,
            config=RunConfig(llm_supports_tool_calling="false"),
        )
        assert record.status == "error" and "vocabulary" in (record.error_detail or "")
