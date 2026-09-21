"""Regression tests for token reconciliation (audit finding A17).

DP-5 Option A calls the reconciliation assertion non-negotiable: "without it,
a silently-zero usage field reads as 'the agentic path is free'."
BUILD-PLAN §7 states the guard as Sum(TraceStep.tokens) == record total.

Two defects were found and are pinned here:
  1. The final generation call added its tokens to the record total but emitted
     no TraceStep, so the sum could never equal the total.
  2. The orchestrator passed the recorder's own cumulative counter into
     reconcile_assert, which compared that value against itself — ratio always
     1.0, so the guard could never fire.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic
from ogr.pipelines.p3_agentic.trace import TraceRecorder


def test_generation_is_emitted_as_a_trace_step():
    recorder = TraceRecorder(route_initial="loop")
    recorder.record("graph_traversal", "Q4", AgentResult(tokens_input=100, tokens_output=20),
                    path_name="traversal")
    recorder.record_llm_generation(tokens_input=5000, tokens_output=400, latency_ms=10.0)

    steps = recorder.finalize()
    assert len(steps) == 2, "Generation must be its own step, not a loose total"
    assert steps[-1].tokens.total == 5400


def test_step_sum_equals_record_total():
    recorder = TraceRecorder(route_initial="loop")
    recorder.record("graph_traversal", "Q4", AgentResult(tokens_input=100, tokens_output=20),
                    path_name="traversal")
    recorder.record_llm_generation(tokens_input=5000, tokens_output=400, latency_ms=10.0)

    assert recorder.trace_token_sum() == recorder.cumulative_tokens().total
    assert recorder.reconcile_assert(recorder.cumulative_tokens().total) is True


def test_reconcile_assert_detects_a_real_mismatch(caplog):
    """The guard must fire on a discrepancy — a tautology cannot."""
    recorder = TraceRecorder(route_initial="loop")
    recorder.record("graph_traversal", "Q4", AgentResult(tokens_input=100, tokens_output=20),
                    path_name="traversal")

    assert recorder.reconcile_assert(99999) is False
    assert "Token reconciliation FAILED" in caplog.text


def test_end_to_end_record_reconciles():
    """The assembled PipelineRecord must satisfy the BUILD-PLAN §7 guard."""
    model = MagicMock()

    def invoke(messages, **_kwargs):
        response = MagicMock()
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        response.response_metadata = {}
        text = " ".join(str(getattr(m, "content", "")) for m in messages).lower()
        if "intent parser" in text:
            response.content = json.dumps({
                "operation": "COUNT",
                "anchor": {"sport": "Sailing", "games": "2016-Summer"},
                "target_field": "event_name",
                "constraints": [],
            })
        else:
            response.content = json.dumps({"answer": "26", "explanation": "e"})
        return response

    model.invoke.side_effect = invoke
    model.bind_tools.return_value = model

    config = RunConfig()
    record = run_p3_agentic(
        query="How many sailing events were held at the 2016 Summer Olympics?",
        llm_model=model,
        tg_client=TigerGraphClient(config=config, mock_chunks=[]),
        entity_linker=EntityLinker(games_vocab=["2016-Summer"], sports_vocab=["Sailing"]),
        config=config,
    )

    step_sum = sum(step.tokens.total for step in (record.trace or []))
    assert step_sum == record.tokens.total, (
        f"sum(TraceStep.tokens)={step_sum} != record total={record.tokens.total}"
    )
    assert record.tokens.total > 0, "A zero cost axis is the failure DP-5 guards against"


def test_intent_parse_tokens_reach_the_cost_axis():
    """The intent parse is P3's entry point; its tokens must not be invisible."""
    model = MagicMock()

    def invoke(messages, **_kwargs):
        response = MagicMock()
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 77, "output_tokens": 11, "total_tokens": 88}
        response.response_metadata = {}
        text = " ".join(str(getattr(m, "content", "")) for m in messages).lower()
        if "intent parser" in text:
            response.content = json.dumps({
                "operation": "COUNT",
                "anchor": {"games": "2016-Summer"},
                "target_field": "event_name",
                "constraints": [],
            })
        else:
            response.content = json.dumps({"answer": "26", "explanation": "e"})
        return response

    model.invoke.side_effect = invoke
    model.bind_tools.return_value = model

    config = RunConfig()
    record = run_p3_agentic(
        query="How many events were held at the 2016 Summer Olympics?",
        llm_model=model,
        tg_client=TigerGraphClient(config=config, mock_chunks=[]),
        entity_linker=EntityLinker(games_vocab=["2016-Summer"]),
        config=config,
    )

    parse_steps = [s for s in (record.trace or []) if s.tool_called == "intent_parser"]
    assert parse_steps, "Intent parse must appear as a TraceStep (DP-5: attribute every call)"
    assert parse_steps[0].tokens.total == 88
