"""The orchestrator's decisions follow the evidence: escalation from an empty
lookup, stop reasons recorded when decided, error records that keep what was
spent, and an evaluator that sees the value being asked about."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.evidence import _evidence_lines
from ogr.pipelines.p3_agentic.orchestrator import evidence_reducer, run_p3_agentic

pytestmark = pytest.mark.usefixtures("fake_embedder")


def _model(intent: dict, groundedness: str = "YES", fail_generation: bool = False) -> MagicMock:
    model = MagicMock()

    def invoke(messages, **_kwargs):
        text = " ".join(str(getattr(m, "content", "")) for m in messages).lower()
        response = MagicMock()
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        response.response_metadata = {}
        if "intent parser" in text:
            response.content = json.dumps(intent)
        elif "groundedness" in text:
            response.content = groundedness
        else:
            if fail_generation:
                raise RuntimeError("generation exploded")
            response.content = json.dumps({"answer": "Usain Bolt", "explanation": "e"})
        return response

    model.invoke.side_effect = invoke
    model.bind_tools.return_value = model
    return model


class _Graph(TigerGraphClient):
    def __init__(self, q1_rows, **kw):
        super().__init__(config=RunConfig(), mock_chunks=[], **kw)  # no live connection
        self.q1_rows = q1_rows
        self.calls = []

    def _run_query(self, name, params):
        self.calls.append(name)
        if name == "q1_lookup":
            return list(self.q1_rows)
        if name == "q4_traverse":
            return [{"event_id": "E0", "event_name": "Men's 100 metres 2004", "doc_id": "Q7"}]
        return []

    def _expand_has_chunk(self, doc_ids):
        return [{"chunk_id": f"{d}_c0", "doc_id": d, "text": "Usain Bolt won the 100 metres.", "seq": 0} for d in doc_ids]


LOOKUP = {"operation": "LOOKUP", "anchor": {"title": "Men's 100 metres"}, "target_field": "gold", "constraints": []}


def _run(model, graph):
    return run_p3_agentic("Who won the Men's 100 metres?", llm_model=model, tg_client=graph,
                          entity_linker=EntityLinker(), config=RunConfig())


def test_a_direct_lookup_reports_its_route_not_an_evaluation():
    graph = _Graph([{"event_id": "E1", "event_name": "Men's 100 metres", "gold": "Usain Bolt", "doc_id": "Q1"}])
    record = _run(_model(LOOKUP), graph)
    assert record.stop_reason == "direct_route"
    assert not any(s.agent_type == "evidence_evaluation" for s in record.trace)
    assert record.strategy_changed is False


def test_an_empty_lookup_escalates_into_the_loop():
    graph = _Graph([])
    record = _run(_model(LOOKUP), graph)
    assert record.strategy_changed is True
    assert any(s.agent_type == "evidence_evaluation" for s in record.trace)
    assert record.stop_reason in {"sufficient_evidence", "no_further_action_available"}


def test_the_trace_names_the_orchestrator_and_the_entity_linker():
    record = _run(_model(LOOKUP), _Graph([{"event_id": "E1", "gold": "Usain Bolt", "doc_id": "Q1"}]))
    kinds = [s.agent_type for s in record.trace]
    assert kinds[:2] == ["orchestrator", "entity_linking"] and kinds[-1] == "answer_generation"


def test_a_failed_run_keeps_the_tokens_it_spent():
    record = _run(_model(LOOKUP, fail_generation=True), _Graph([{"event_id": "E1", "gold": "Usain Bolt"}]))
    assert record.status == "error"
    assert record.tokens.total >= 15, "the intent parse was paid for"
    assert record.trace


def test_the_evaluator_sees_the_field_asked_about():
    lines = _evidence_lines([{"event_id": "E1", "event_name": "Men's 100 metres", "gold": "Usain Bolt",
                              "source": "graph_traversal"}])
    assert "Usain Bolt" in lines[0]


def test_evidence_is_never_held_twice():
    row = {"event_id": "E1", "gold": "Usain Bolt"}
    assert evidence_reducer([row], [dict(row), {"event_id": "E2"}]) == [row, {"event_id": "E2"}]
