"""Tests for Group 5: Orchestrator and full pipeline conformance.

Verification Plan Group 5:
- test_p3_conforms_to_pipeline_record_and_tracestep
- test_paraphrase_set_same_intents
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ogr.common.contracts import PipelineRecord, TraceStep, TokenUsage
from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.trace import TraceRecorder
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult

PARAPHRASE_FILE = (
    Path(__file__).resolve().parents[4]
    / "acceptance"
    / "paraphrase"
    / "paraphrase_set.jsonl"
)


def _make_mock_llm(answer="10", explanation="Based on the evidence.") -> MagicMock:
    """Create a mock LLM that returns a valid CORE-02 response."""
    model = MagicMock()
    resp = MagicMock()
    resp.content = json.dumps({"answer": answer, "explanation": explanation})
    resp.tool_calls = []
    resp.usage_metadata = {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}
    resp.response_metadata = {}
    model.invoke.return_value = resp
    model.bind_tools.return_value = model
    return model


def _make_mock_client() -> TigerGraphClient:
    """Create a TigerGraph client with empty mocks (offline-safe)."""
    return TigerGraphClient(config=RunConfig(), mock_chunks=[])


def _make_linker() -> EntityLinker:
    return EntityLinker(
        games_vocab=["2016-Summer", "2012-Summer", "2008-Summer"],
        sports_vocab=["Sailing", "Swimming", "Athletics"],
        venues_vocab=["Aquatics Centre", "Olympic Stadium"],
    )


class TestP3ConformsToContract:
    """test_p3_conforms_to_pipeline_record_and_tracestep"""

    def test_pipeline_record_has_required_fields(self):
        """PipelineRecord must have all CORE-02 fields: answer, explanation, citations, tokens, trace."""
        # Instantiate a minimal PipelineRecord
        record = PipelineRecord(
            pipeline="agentic_graphrag",
            answer="10",
            explanation="There were 10 events.",
            citations=[],
            chunks_returned=2,
            citations_count=2,
            tokens=TokenUsage(input=100, output=50, total=150),
            token_source="provider",
            latency_ms=120.0,
            trace=[],
            strategy_changed=False,
            stop_reason="sufficient_evidence",
            status="done",
        )
        assert record.answer == "10"
        assert record.explanation != ""
        assert isinstance(record.tokens, TokenUsage)
        assert record.trace is not None
        assert record.stop_reason in {
            "sufficient_evidence", "step_budget_exhausted", "token_budget_exhausted",
            "no_further_action_available", "disambiguation_required", "error",
        }
        assert record.pipeline == "agentic_graphrag"

    def test_trace_step_has_required_fields(self):
        """TraceStep must include chunks_returned and citations_count (PLAN-004 DP-1)."""
        step = TraceStep(
            step_n=1,
            agent_type="graph_traversal",
            tool_called="Q4",
            tokens=TokenUsage(input=50, output=20, total=70),
            chunks_returned=3,
            citations_count=3,
            latency_ms=45.0,
            strategy_change=False,
            notes="Q4 traverse: edge=PREV_EDITION",
        )
        assert step.chunks_returned == 3
        assert step.citations_count == 3
        assert step.strategy_change is False
        assert step.step_n == 1

    def test_trace_recorder_produces_trace_steps(self):
        """TraceRecorder.record() produces TraceStep objects conforming to the schema."""
        recorder = TraceRecorder(route_initial="loop")
        result = AgentResult(
            evidence=[{"doc_id": "Q100", "source": "graph_traversal"}],
            chunks_returned=1,
            citations_count=1,
            latency_ms=55.0,
            tokens_input=80,
            tokens_output=30,
            notes="Q4 traverse",
        )
        step = recorder.record("graph_traversal", "Q4", result)
        assert isinstance(step, TraceStep)
        assert step.step_n == 1
        assert step.tokens.input == 80
        assert step.tokens.output == 30
        assert step.chunks_returned == 1
        assert step.citations_count == 1

    def test_token_reconciliation_asserts_on_large_discrepancy(self, caplog):
        """Reconciliation assertion logs a warning when trace_sum differs wildly from record_total."""
        import logging
        recorder = TraceRecorder(route_initial="loop")
        result = AgentResult(
            chunks_returned=1, citations_count=1, latency_ms=10.0,
            tokens_input=100, tokens_output=50,
        )
        recorder.record("graph_traversal", "Q4", result)  # sum = 150

        with caplog.at_level(logging.WARNING):
            recorder.reconcile_assert(record_total_tokens=10)  # wildly mismatched

        assert any("reconciliation" in msg.lower() for msg in caplog.messages)

    def test_p3_run_produces_pipeline_record(self):
        """Integration smoke test: run_p3_agentic produces a valid PipelineRecord."""
        from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic

        mock_llm = _make_mock_llm(answer="26", explanation="There were 26 nations.")
        client = _make_mock_client()
        linker = _make_linker()
        config = RunConfig()

        record = run_p3_agentic(
            query="How many nations competed in Sailing at the 2016 Olympics?",
            llm_model=mock_llm,
            tg_client=client,
            entity_linker=linker,
            config=config,
        )

        assert isinstance(record, PipelineRecord)
        assert record.pipeline == "agentic_graphrag"
        assert isinstance(record.answer, str)
        assert isinstance(record.explanation, str)
        assert record.trace is not None
        assert isinstance(record.strategy_changed, bool)
        assert record.stop_reason in {
            "sufficient_evidence", "step_budget_exhausted", "token_budget_exhausted",
            "no_further_action_available", "disambiguation_required", "error",
        }

    def test_lookup_question_routes_zero_loop_edges(self):
        """LOOKUP with fully-specified anchor must traverse ZERO loop edges.

        From implementation-plan-AGENT.md Group 5:
        'LOOKUP must traverse zero loop edges. If the graph is built so that every
        question passes through evaluate_evidence, necessity routing exists on paper only.'
        """
        from ogr.pipelines.p3_agentic.orchestrator import build_p3_graph

        config = RunConfig()
        client = _make_mock_client()
        linker = _make_linker()

        # Sequence: intent parse returns valid LOOKUP, generation returns answer
        # Using a counter-based side_effect so it never runs out
        call_count = [0]

        def mock_invoke(messages):
            call_count[0] += 1
            resp = MagicMock()
            resp.tool_calls = []
            resp.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
            resp.response_metadata = {}
            if call_count[0] == 1:
                # First call: intent parse
                resp.content = json.dumps({
                    "operation": "LOOKUP",
                    "anchor": {"title": "Athletics at the 2016 Summer Olympics – Men's marathon"},
                    "target_field": "nations",
                    "constraints": [],
                })
            else:
                # All subsequent calls: generation
                resp.content = json.dumps({"answer": "193", "explanation": "193 nations competed."})
            return resp

        model = MagicMock()
        model.invoke.side_effect = mock_invoke
        model.bind_tools.return_value = model

        compiled, state_store = build_p3_graph(model, client, linker, config)
        compiled.invoke({"question": "How many nations competed in the men's marathon at the 2016 Olympics?"})

        record = state_store.get("pipeline_record")
        assert record is not None
        assert isinstance(record, PipelineRecord)
        assert record.answer == "193"
        assert record.stop_reason in {
            "sufficient_evidence", "step_budget_exhausted", "token_budget_exhausted",
            "no_further_action_available", "disambiguation_required", "error",
        }
        # LOOKUP routes directly to generate — model.invoke called exactly TWICE
        # (once for intent parse, once for generation). If loop ran, it would be called more.
        assert call_count[0] == 2, (
            f"Expected exactly 2 LLM calls (intent + generation) for LOOKUP path, "
            f"got {call_count[0]}. Necessity routing may be passing through the evidence loop."
        )




class TestParaphraseSetSameIntents:
    """test_paraphrase_set_same_intents: Paraphrase set exists and each entry has required fields."""

    def test_paraphrase_set_exists(self):
        """Paraphrase set file must exist at acceptance/paraphrase/paraphrase_set.jsonl."""
        assert PARAPHRASE_FILE.exists(), (
            f"Paraphrase set not found at {PARAPHRASE_FILE}. "
            "This file is required for anti-overfitting evidence (FR-16, NFR-7)."
        )

    def test_paraphrase_set_has_15_entries(self):
        """Paraphrase set must have ~15 entries (the anti-overfitting evidence)."""
        entries = [json.loads(line) for line in PARAPHRASE_FILE.read_text().strip().splitlines()]
        assert len(entries) >= 15, f"Expected >=15 paraphrase entries, got {len(entries)}"

    def test_paraphrase_entries_have_required_fields(self):
        """Each paraphrase entry must have id, original_id, question, intent."""
        for line in PARAPHRASE_FILE.read_text().strip().splitlines():
            entry = json.loads(line)
            assert "id" in entry, f"Missing 'id': {entry}"
            assert "original_id" in entry, f"Missing 'original_id': {entry}"
            assert "question" in entry, f"Missing 'question': {entry}"
            assert "intent" in entry, f"Missing 'intent': {entry}"
            assert "operation" in entry["intent"], f"Missing 'operation' in intent: {entry}"

    def test_paraphrase_operations_in_vocabulary(self):
        """All paraphrase intents use valid operation types."""
        valid_ops = {"LOOKUP", "COUNT", "ARGMAX", "TRAVERSE"}
        for line in PARAPHRASE_FILE.read_text().strip().splitlines():
            entry = json.loads(line)
            op = entry["intent"]["operation"]
            assert op in valid_ops, f"Invalid operation '{op}' in entry {entry['id']}"

    def test_no_qtype_in_paraphrase_set(self):
        """qtype must not appear in the paraphrase set — it is an eval-set label."""
        content = PARAPHRASE_FILE.read_text()
        assert '"qtype"' not in content, (
            "NFR-7 violation: 'qtype' key found in paraphrase_set.jsonl. "
            "qtype is an eval-set label and must not appear."
        )

    def test_paraphrase_ids_are_unique(self):
        """Paraphrase IDs must be unique."""
        ids = [json.loads(line)["id"] for line in PARAPHRASE_FILE.read_text().strip().splitlines()]
        assert len(ids) == len(set(ids)), "Duplicate IDs found in paraphrase set"
