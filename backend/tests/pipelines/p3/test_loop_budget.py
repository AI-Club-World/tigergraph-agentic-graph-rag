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

CLOSED_STOP_VOCABULARY = {
    "sufficient_evidence",
    "step_budget_exhausted",
    "token_budget_exhausted",
    "no_further_action_available",
    "disambiguation_required",
    "error",
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


def test_unsatisfiable_loop_stops_on_step_budget():
    """A question whose evidence never satisfies must stop on a DP-3 budget."""
    record = _run(groundedness="NO")

    assert record.status == "done", (
        f"Loop did not terminate cleanly: {record.error_detail}. "
        "Hitting the recursion limit means both budgets are inert."
    )
    assert record.stop_reason == "step_budget_exhausted"
    assert record.stop_reason in CLOSED_STOP_VOCABULARY


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
