"""Regression tests for the loop budget (audit findings A18 / A19).

Before the fix the graph ran on StateGraph(dict), where a node returning
{"path_taken": [x]} REPLACES the list instead of appending. step_count =
len(path_taken) therefore never grew, and because the loop's only LLM call
(the groundedness check) was made outside the accounting module, tokens_used
never grew either. Both DP-3 budgets were inert: a TRAVERSE question whose
evidence never satisfies ran 10,007 iterations and died on LangGraph's
recursion limit.

implementation-plan-AGENT.md stop condition: "The loop fails to terminate
within budget on any question."
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.orchestrator import append_reducer, run_p3_agentic

import pytest

# Query embedding is strict (never hash noise): a stand-in model serves it here.
pytestmark = pytest.mark.usefixtures("fake_embedder")

CLOSED_STOP_VOCABULARY = {
    "sufficient_evidence",
    "step_budget_exhausted",
    "token_budget_exhausted",
    "no_further_action_available",
    "disambiguation_required",
    "error",
    "direct_route",
}


def _mock_llm(groundedness: str = "NO") -> MagicMock:
    """LLM that parses a TRAVERSE intent and answers the groundedness gate."""
    model = MagicMock()

    def invoke(messages, **_kwargs):
        response = MagicMock()
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        response.response_metadata = {}
        text = " ".join(str(getattr(m, "content", "")) for m in messages).lower()
        if "intent parser" in text:
            response.content = json.dumps({
                "operation": "TRAVERSE",
                "anchor": {"games": "2012-Summer"},
                "target_field": "gold",
                "constraints": [],
            })
        elif "groundedness" in text:
            response.content = groundedness
        else:
            response.content = json.dumps({"answer": "United States", "explanation": "e"})
        return response

    model.invoke.side_effect = invoke
    model.bind_tools.return_value = model
    return model


def _run(groundedness: str, chunks=None, **config_kwargs):
    config = RunConfig(**config_kwargs)
    return run_p3_agentic(
        query="Which nation won the most golds at the Games before the 2012 Summer Olympics?",
        llm_model=_mock_llm(groundedness),
        tg_client=TigerGraphClient(config=config, mock_chunks=chunks or []),
        entity_linker=EntityLinker(games_vocab=["2012-Summer", "2008-Summer"]),
        config=config,
    )


def test_append_reducer_accumulates():
    """The reducer must append, not replace — this is what arms the step budget."""
    assert append_reducer(["a"], ["b"]) == ["a", "b"]
    assert append_reducer(None, ["a"]) == ["a"]
    assert append_reducer(["a"], None) == ["a"]


def _tool_steps(record):
    return [s.tool_called for s in record.trace if s.agent_type not in (
        "orchestrator", "entity_linking", "evidence_evaluation", "answer_generation")]


def test_unsatisfiable_loop_stops_without_repeating_itself():
    """A question whose evidence never satisfies must terminate — and once
    every applicable tool has run and nothing new comes back, it stops then
    (no_further_action_available) instead of re-running the same queries
    until the step budget."""
    record = _run(groundedness="NO")

    assert record.status == "done", (
        f"Loop did not terminate cleanly: {record.error_detail}. "
        "Hitting the recursion limit means both budgets are inert."
    )
    assert record.stop_reason == "no_further_action_available"
    tools = _tool_steps(record)
    assert len(tools) == len(set(tools)), f"an action repeated: {tools}"


def test_loop_respects_a_lowered_step_budget():
    """max_steps comes from run_config and actually bounds the loop."""
    tight = _run(groundedness="NO", max_steps=2)
    loose = _run(groundedness="NO", max_steps=6)

    assert tight.stop_reason == "step_budget_exhausted"
    assert len(tight.trace) < len(loose.trace), (
        "A lower max_steps must produce a shorter trace; if it does not, "
        "step_count is not being read from an accumulating path_taken."
    )


def test_sufficient_evidence_stops_before_the_budget():
    """AD-3: sufficiency is the primary stop signal, the budget is a safety valve."""
    chunks = [
        {
            "chunk_id": f"Q1_c{i}",
            "doc_id": "Q1",
            "text": "United States won the most gold medals in athletics in 2008",
            "vtype": "Chunk",
        }
        for i in range(3)
    ]
    record = _run(groundedness="YES", chunks=chunks)

    assert record.status == "done"
    assert record.stop_reason == "sufficient_evidence"



class _StaticGraphClient(TigerGraphClient):
    """Every traversal and document expansion returns the same rows, so each
    loop iteration after the second adds no new evidence."""

    def _run_query(self, query_name, params):
        if query_name == "q4_traverse":
            return [{"event_id": "E1", "event_name": "Men's 100 metres 2008"}]
        return [{"value": "Jamaica", "doc_id": "Q9"}]

    def _expand_has_chunk(self, doc_ids):
        return [{"chunk_id": "Q9_c0", "doc_id": "Q9", "text": "Jamaica won the final.", "seq": 0}]


def _groundedness_calls(model) -> int:
    return sum(
        "groundedness" in " ".join(str(getattr(m, "content", "")) for m in call.args[0]).lower()
        for call in model.invoke.call_args_list
    )


def test_unchanged_evidence_reuses_the_groundedness_verdict():
    """Deterministic-first: an iteration adding no new evidence must not pay
    for a second, identical groundedness call."""
    model = _mock_llm("NO")
    intent = json.dumps({"operation": "TRAVERSE", "anchor": {"title": "Men's 100 metres"}, "constraints": []})
    base = model.invoke.side_effect

    def invoke(messages, **kwargs):
        response = base(messages, **kwargs)
        if "intent parser" in " ".join(str(getattr(m, "content", "")) for m in messages).lower():
            response.content = intent
        return response

    model.invoke.side_effect = invoke
    config = RunConfig()
    record = run_p3_agentic(
        query="Who won the event after the Men's 100 metres?",
        llm_model=model,
        tg_client=_StaticGraphClient(config=config),
        entity_linker=EntityLinker(),
        config=config,
    )
    evaluations = [s for s in record.trace if s.agent_type == "evidence_evaluation"]
    reused = [s for s in evaluations if "verdict reused" in s.notes]
    assert reused and all(s.tokens.total == 0 for s in reused)
    # One paid groundedness call per distinct evidence state, none for a repeat.
    assert _groundedness_calls(model) == len(evaluations) - len(reused)
    assert record.stop_reason == "no_further_action_available"
    tools = _tool_steps(record)
    assert len(tools) == len(set(tools)), f"an action repeated: {tools}"
    assert len({(c.source_id, c.chunk_id) for c in record.citations}) == len(record.citations)
    assert sum(s.tokens.total for s in record.trace) == record.tokens.total
