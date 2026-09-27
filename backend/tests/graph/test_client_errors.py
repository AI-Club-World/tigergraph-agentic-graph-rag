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
