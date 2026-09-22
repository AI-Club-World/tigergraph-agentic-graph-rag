"""Tests for GRAPH-08: the P2 GraphRAG pipeline.

implementation-plan-GRAPH.md Group 4 verification: "P2 output validates
against PipelineRecord" (G2).

The load-bearing property is the ablation. P2 must differ from P3 by exactly
one variable — the loop — so these tests pin that it shares P3's intent parser,
runs exactly one query, and never traces or loops.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.common.contracts import PipelineRecord
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p2_graphrag import (
    format_evidence_into_context,
    run_p2_graphrag,
    select_single_query,
)
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.intent import Anchor, IntentSchema


def _linker() -> EntityLinker:
    return EntityLinker(
        games_vocab=["2016-Summer", "2012-Summer"],
        sports_vocab=["Sailing", "Athletics"],
        venues_vocab=["Olympic Stadium"],
    )


def _model(intent: dict, answer: str = "26") -> MagicMock:
    model = MagicMock()

    def invoke(messages, **_kwargs):
        response = MagicMock()
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
        response.response_metadata = {}
        text = " ".join(str(getattr(m, "content", "")) for m in messages).lower()
        if "intent parser" in text:
            response.content = json.dumps(intent)
        else:
            response.content = json.dumps({"answer": answer, "explanation": "From the graph."})
        return response

    model.invoke.side_effect = invoke
    model.bind_tools.return_value = model
    return model


class _CountingClient(TigerGraphClient):
    """Records every installed query P2 runs, so 'exactly one' is checkable."""

    def __init__(self, config: RunConfig, rows: list[dict] | None = None):
        super().__init__(config=config, mock_chunks=[])
        self.calls: list[str] = []
        self._rows = rows if rows is not None else [{"event_id": "E1", "doc_id": "Q1", "nations": 26}]

    def _run_query(self, query_name: str, params: dict) -> list[dict]:
        self.calls.append(query_name)
        return list(self._rows)


class TestSingleQuerySelection:
    def test_fully_specified_lookup_selects_lookup(self):
        intent = IntentSchema(
            operation="LOOKUP",
            anchor=Anchor(title="Sailing at the 2016 Summer Olympics"),
            target_field="nations",
        )
        assert select_single_query(intent) == "lookup"

    def test_count_selects_aggregate(self):
        assert select_single_query(IntentSchema(operation="COUNT")) == "aggregate"

    def test_argmax_selects_aggregate(self):
        assert select_single_query(IntentSchema(operation="ARGMAX")) == "aggregate"

    def test_traverse_selects_traverse(self):
        assert select_single_query(IntentSchema(operation="TRAVERSE")) == "traverse"

    def test_underspecified_lookup_still_runs_one_query(self):
        """Where P3 would loop, P2 runs the first step and stops. That is the experiment."""
        assert select_single_query(IntentSchema(operation="LOOKUP")) == "traverse"


class TestExactlyOneQuery:
    def test_lookup_runs_exactly_one_query(self):
        config = RunConfig()
        client = _CountingClient(config)
        run_p2_graphrag(
            "Which nation won the sailing event?",
            client=client,
            config=config,
            model=_model({
                "operation": "LOOKUP",
                "anchor": {"title": "Sailing at the 2016 Summer Olympics"},
                "target_field": "nations",
                "constraints": [],
            }),
            entity_linker=_linker(),
        )
        assert client.calls == ["q1_lookup"], f"P2 must run exactly one query, ran {client.calls}"

    def test_traverse_does_not_loop(self):
        """No evidence check means no second traversal, even with empty results."""
        config = RunConfig()
        client = _CountingClient(config, rows=[])
        record = run_p2_graphrag(
            "Which Games came before the 2012 Summer Olympics?",
            client=client,
            config=config,
            model=_model({
                "operation": "TRAVERSE",
                "anchor": {"games": "2012-Summer", "title": "Athletics 2012"},
                "target_field": "gold",
                "constraints": [],
            }),
            entity_linker=_linker(),
        )
        assert len(client.calls) == 1, f"P2 looped: {client.calls}"
        assert record.status == "done"


class TestRecordConformance:
    def _run(self):
        config = RunConfig()
        return run_p2_graphrag(
            "How many nations competed in Sailing at the 2016 Summer Olympics?",
            client=_CountingClient(config),
            config=config,
            model=_model({
                "operation": "COUNT",
                "anchor": {"sport": "Sailing", "games": "2016-Summer"},
                "target_field": "nations",
                "constraints": [],
            }),
            entity_linker=_linker(),
        )

    def test_conforms_to_pipeline_record(self):
        record = self._run()
        assert isinstance(record, PipelineRecord)
        assert record.pipeline == "graphrag"
        assert record.answer == "26"
        assert record.status == "done"

    def test_has_no_trace_no_strategy_no_stop_reason(self):
        """P2 has no loop, so it has nothing to trace and no stopping decision."""
        record = self._run()
        assert record.trace is None
        assert record.strategy_changed is None
        assert record.stop_reason is None

    def test_counts_both_the_intent_parse_and_the_generation(self):
        """Two LLM calls at 50 tokens each; omitting the parse would understate P2."""
        record = self._run()
        assert record.tokens.total == 100, (
            "P2's cost must include its intent parse, or the P3-vs-P2 comparison "
            "credits P2 with a free parse that P3 is charged for."
        )

    def test_citations_are_entity_refs_with_a_source_id(self):
        record = self._run()
        assert record.citations
        assert all(c.source_id for c in record.citations)
        assert record.citations[0].ref_type == "entity"
        assert record.citations_count == len(record.citations)

    def test_json_round_trip(self):
        record = self._run()
        assert PipelineRecord.model_validate_json(record.model_dump_json()).answer == "26"


class TestFaultIsolation:
    def test_generation_failure_yields_an_error_record_not_an_exception(self):
        config = RunConfig()
        model = _model({"operation": "COUNT", "anchor": {}, "target_field": "nations",
                        "constraints": []})
        calls = {"n": 0}
        original = model.invoke.side_effect

        def flaky(messages, **kwargs):
            calls["n"] += 1
            if calls["n"] > 1:  # let the intent parse through, fail generation
                raise RuntimeError("provider exploded")
            return original(messages, **kwargs)

        model.invoke.side_effect = flaky
        record = run_p2_graphrag("q", client=_CountingClient(config), config=config,
                                 model=model, entity_linker=_linker())

        assert record.status == "error"
        assert "provider exploded" in record.error_detail
        assert record.pipeline == "graphrag"


class TestContextFormatting:
    def test_empty_evidence_is_stated_not_faked(self):
        assert "No relevant graph results" in format_evidence_into_context([])

    def test_includes_the_source_id(self):
        context = format_evidence_into_context([{"doc_id": "Q1", "event_name": "Men's marathon"}])
        assert "Q1" in context and "Men's marathon" in context
