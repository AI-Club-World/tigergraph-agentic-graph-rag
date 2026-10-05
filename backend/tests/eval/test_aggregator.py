"""Tests for EVAL-03 aggregation and the verdict block.

The cost-honesty case is tested explicitly: the benchmark is meant to surface
questions where the agentic path is *not* worth its multiplier, so a verdict
that only ever flatters the agent would be a defect, not a good result.
"""

from __future__ import annotations

from ogr.common.contracts import Citation, PipelineRecord, QueryLevelRecord, TokenUsage
from ogr.eval.aggregator import aggregate_query, build_verdict


def _record(pipeline: str, answer: str, total: int) -> PipelineRecord:
    return PipelineRecord(
        pipeline=pipeline,  # type: ignore[arg-type]
        answer=answer,
        explanation="e",
        citations=[Citation(source_id="Q1", chunk_id=None, ref_type="entity")],
        tokens=TokenUsage(input=total, output=0, total=total),
    )


def _three(rag_answer="China", graph_answer="United States", agentic_answer="United States",
           rag_tokens=2000, graph_tokens=800, agentic_tokens=10000):
    return {
        "rag": _record("rag", rag_answer, rag_tokens),
        "graphrag": _record("graphrag", graph_answer, graph_tokens),
        "agentic_graphrag": _record("agentic_graphrag", agentic_answer, agentic_tokens),
    }


class TestTokenMultipliers:
    def test_hand_computed_multipliers(self):
        """agentic 10000 / rag 2000 = 5.0; / graphrag 800 = 12.5"""
        verdict = build_verdict(_three(), ["United States"])
        assert verdict.token_multiplier_vs_rag == 5.0
        assert verdict.token_multiplier_vs_graphrag == 12.5

    def test_zero_denominator_does_not_crash(self):
        records = _three(rag_tokens=0)
        assert build_verdict(records, ["United States"]).token_multiplier_vs_rag is None  # undefined, not 0


class TestAccuracyDeltas:
    def test_agentic_correct_rag_wrong(self):
        verdict = build_verdict(_three(), ["United States"])
        assert verdict.accuracy_delta_vs_rag == 1.0
        assert verdict.accuracy_delta_vs_graphrag == 0.0

    def test_agentic_wrong_rag_correct_is_negative(self):
        """A negative delta must be representable — the agent does not always win."""
        records = _three(rag_answer="United States", agentic_answer="China")
        verdict = build_verdict(records, ["United States"])
        assert verdict.accuracy_delta_vs_rag == -1.0
        assert "lost to RAG" in verdict.summary_line

    def test_all_correct_is_zero_delta(self):
        records = _three(rag_answer="United States")
        verdict = build_verdict(records, ["United States"])
        assert verdict.accuracy_delta_vs_rag == 0.0


class TestVerdictNAWithoutGroundTruth:
    """test_verdict_na_without_ground_truth (FR-9)."""

    def test_no_gold_gives_na_not_zero(self):
        verdict = build_verdict(_three(), gold_variants=None)
        assert verdict.accuracy_delta_vs_rag == "n/a"
        assert verdict.accuracy_delta_vs_graphrag == "n/a"

    def test_empty_gold_list_gives_na(self):
        assert build_verdict(_three(), gold_variants=[]).accuracy_delta_vs_rag == "n/a"

    def test_token_multipliers_still_computed_without_gold(self):
        """Cost is measurable even when accuracy is not."""
        verdict = build_verdict(_three(), gold_variants=None)
        assert verdict.token_multiplier_vs_rag == 5.0

    def test_na_is_reported_in_the_summary(self):
        assert "N/A" in build_verdict(_three(), None).summary_line


class TestCostHonesty:
    """At least one shape must show the agent not being worth its multiplier."""

    def test_overkill_case_reads_as_no_gain(self):
        records = _three(rag_answer="Usain Bolt", graph_answer="Usain Bolt",
                         agentic_answer="Usain Bolt", agentic_tokens=8000)
        verdict = build_verdict(records, ["Usain Bolt"])
        assert verdict.accuracy_delta_vs_rag == 0.0
        assert verdict.token_multiplier_vs_rag == 4.0
        assert "No accuracy gain" in verdict.summary_line


class TestAggregateQuery:
    def test_produces_a_conforming_query_level_record(self):
        record = aggregate_query(
            query_id="q-1",
            query_text="Which nation won the most golds?",
            records=_three(),
            gold_variants=["United States"],
            qtype="multi_hop",
        )
        assert isinstance(record, QueryLevelRecord)
        assert set(record.pipelines) == {"rag", "graphrag", "agentic_graphrag"}
        assert record.qtype == "multi_hop"
        assert record.timestamp
        assert record.verdict.token_multiplier_vs_rag == 5.0

    def test_partial_results_still_aggregate(self):
        """NFR-2: two pipelines must render when the third is missing."""
        records = _three()
        del records["graphrag"]
        record = aggregate_query("q-1", "q", records, ["United States"])
        assert set(record.pipelines) == {"rag", "agentic_graphrag"}
        assert record.verdict.token_multiplier_vs_graphrag is None
        assert record.verdict.accuracy_delta_vs_rag == 1.0

    def test_round_trips_through_json(self):
        """The record contract is what the API and the batch store serialise."""
        record = aggregate_query("q-1", "q", _three(), ["United States"])
        restored = QueryLevelRecord.model_validate_json(record.model_dump_json())
        assert restored.verdict.accuracy_delta_vs_rag == 1.0

    def test_na_survives_json_round_trip(self):
        record = aggregate_query("q-1", "q", _three(), None)
        restored = QueryLevelRecord.model_validate_json(record.model_dump_json())
        assert restored.verdict.accuracy_delta_vs_rag == "n/a"


class TestNoCostRatioForAFailedRun:
    """UI check: an errored Agentic run showed "Agentic cost 0.2x RAG tokens"."""

    def test_errored_agentic_has_no_ratio_and_says_why(self):
        records = {
            "rag": _record("rag", "Usain Bolt", 6357),
            "graphrag": _record("graphrag", "Not enough information", 9788),
            "agentic_graphrag": _record("agentic_graphrag", "", 1298).model_copy(update={"status": "error"}),
        }
        verdict = build_verdict(records, gold_variants=None)
        assert verdict.token_multiplier_vs_rag is None
        assert verdict.token_multiplier_vs_graphrag is None
        assert "Agentic GraphRAG errored: no cost ratio" in verdict.summary_line

    def test_errored_baseline_has_no_ratio_against_it_only(self):
        records = {
            "rag": _record("rag", "", 0).model_copy(update={"status": "error"}),
            "graphrag": _record("graphrag", "x", 2000),
            "agentic_graphrag": _record("agentic_graphrag", "x", 1000),
        }
        verdict = build_verdict(records, gold_variants=["x"])
        assert verdict.token_multiplier_vs_rag is None
        assert verdict.token_multiplier_vs_graphrag == 0.5
        assert "RAG errored: no cost ratio" in verdict.summary_line
