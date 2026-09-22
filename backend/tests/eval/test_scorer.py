"""Tests for EVAL-02: EM, token F1 and retrieval metrics.

implementation-plan-UI.md Group 1 names test_em_f1_matches_hand_computed, and
its manual step makes hand-computed agreement the G3 trigger. The F1 cases
below carry their arithmetic in the assertion so the expected value is
checkable by eye rather than copied from a previous run.

NFR-6: nothing in this path calls a model or the network.
"""

from __future__ import annotations

import pytest

from ogr.common.contracts import Citation, PipelineRecord, PipelineScores
from ogr.eval.scorer import (
    aggregate,
    aggregate_by_qtype,
    exact_match,
    retrieval_metrics,
    score_answer,
    score_record,
    token_f1,
)


class TestExactMatch:
    def test_identical_answer(self):
        assert exact_match("Usain Bolt", ["Usain Bolt"]) == 1.0

    def test_normalization_applies(self):
        assert exact_match("the United States!", ["United States"]) == 1.0

    def test_wrong_answer(self):
        assert exact_match("China", ["United States"]) == 0.0

    def test_max_over_gold_variants(self):
        assert exact_match("USA", ["United States", "USA"]) == 1.0

    def test_no_gold_scores_zero(self):
        assert exact_match("United States", []) == 0.0

    def test_empty_prediction_scores_zero(self):
        assert exact_match("", ["United States"]) == 0.0

    def test_multi_person_scored_as_a_set(self):
        """§9: concatenated names are compared as sets, so order cannot matter."""
        assert exact_match("John DoeJane Smith", ["Jane SmithJohn Doe"]) == 1.0

    def test_maclennan_is_not_mis_split_into_a_wrong_answer(self):
        """The pub-067 regression: without the guard this scores 0."""
        assert exact_match("Rosannagh MacLennan", ["Rosannagh MacLennan"]) == 1.0


class TestTokenF1:
    def test_exact_answer_is_one(self):
        assert token_f1("Usain Bolt", ["Usain Bolt"]) == 1.0

    def test_no_overlap_is_zero(self):
        assert token_f1("China", ["United States"]) == 0.0

    def test_hand_computed_partial_overlap(self):
        """prediction 3 tokens, gold 2 tokens, 2 shared.

        precision = 2/3, recall = 2/2 = 1, F1 = 2*(2/3)/(2/3 + 1) = 0.8
        """
        assert token_f1("the United States team", ["United States"]) == pytest.approx(0.8)

    def test_hand_computed_one_of_three(self):
        """prediction 2 tokens, gold 3 tokens, 1 shared.

        precision = 1/2, recall = 1/3, F1 = 2*(1/6)/(5/6) = 0.4
        """
        assert token_f1("marathon gold", ["mens marathon event"]) == pytest.approx(0.4)

    def test_max_over_gold_variants(self):
        assert token_f1("USA", ["United States", "USA"]) == 1.0

    def test_empty_prediction(self):
        assert token_f1("", ["United States"]) == 0.0


class TestRetrievalMetrics:
    def test_perfect_retrieval(self):
        precision, recall, f1 = retrieval_metrics(["Q1", "Q2"], ["Q1", "Q2"])
        assert (precision, recall, f1) == (1.0, 1.0, 1.0)

    def test_hand_computed_partial(self):
        """retrieved {Q1,Q2,Q3}, gold {Q1,Q2,Q4}: hits 2.

        precision = 2/3, recall = 2/3, F1 = 2/3
        """
        precision, recall, f1 = retrieval_metrics(["Q1", "Q2", "Q3"], ["Q1", "Q2", "Q4"])
        assert precision == pytest.approx(2 / 3)
        assert recall == pytest.approx(2 / 3)
        assert f1 == pytest.approx(2 / 3)

    def test_duplicate_citations_do_not_inflate_precision(self):
        """Citing one parent document twice is not retrieving it twice."""
        precision, recall, _ = retrieval_metrics(["Q1", "Q1", "Q1"], ["Q1"])
        assert precision == 1.0
        assert recall == 1.0

    def test_no_gold_scores_zero(self):
        assert retrieval_metrics(["Q1"], []) == (0.0, 0.0, 0.0)

    def test_no_retrieval_scores_zero(self):
        assert retrieval_metrics([], ["Q1"]) == (0.0, 0.0, 0.0)

    def test_empty_ids_are_ignored(self):
        precision, _, _ = retrieval_metrics(["Q1", ""], ["Q1"])
        assert precision == 1.0


class TestCompletenessIsRecall:
    """DP-2 Option A: Completeness is an explicit alias of Recall."""

    def test_completeness_equals_recall(self):
        scores = score_answer(
            "United States",
            ["United States"],
            retrieved_doc_ids=["Q1", "Q2", "Q3"],
            gold_doc_ids=["Q1", "Q2", "Q4", "Q5"],
        )
        assert scores.completeness == scores.recall
        assert scores.recall == pytest.approx(0.5)  # 2 hits / 4 gold


class TestScoreRecord:
    def _record(self, answer: str, source_ids: list[str]) -> PipelineRecord:
        return PipelineRecord(
            pipeline="rag",
            answer=answer,
            explanation="Prose that must never be scored. United States United States.",
            citations=[Citation(source_id=s, chunk_id=None, ref_type="entity") for s in source_ids],
        )

    def test_scores_the_answer_span_not_the_explanation(self):
        """PLAT-06: EM and F1 score `answer` only."""
        record = self._record("China", ["Q1"])
        scores = score_record(record, ["United States"], ["Q1"])
        assert scores.em == 0.0, "The explanation mentioned the gold answer and must not count"
        assert scores.f1 == 0.0

    def test_retrieval_comes_from_citation_source_ids(self):
        record = self._record("United States", ["Q1", "Q2"])
        scores = score_record(record, ["United States"], ["Q1", "Q2"])
        assert scores.em == 1.0
        assert scores.precision == 1.0
        assert scores.recall == 1.0


class TestAggregation:
    def test_mean_of_scores(self):
        combined = aggregate([
            PipelineScores(em=1.0, f1=1.0, precision=1.0, recall=1.0, completeness=1.0),
            PipelineScores(em=0.0, f1=0.5, precision=0.5, recall=0.5, completeness=0.5),
        ])
        assert combined.em == 0.5
        assert combined.f1 == 0.75

    def test_empty_aggregate_is_zero_not_an_error(self):
        assert aggregate([]).em == 0.0

    def test_per_qtype_breakdown(self):
        breakdown = aggregate_by_qtype([
            ("lookup", PipelineScores(em=1.0)),
            ("lookup", PipelineScores(em=0.0)),
            ("aggregation", PipelineScores(em=1.0)),
        ])
        assert breakdown["lookup"].em == 0.5
        assert breakdown["aggregation"].em == 1.0

    def test_missing_qtype_buckets_as_unknown(self):
        breakdown = aggregate_by_qtype([(None, PipelineScores(em=1.0))])
        assert breakdown["unknown"].em == 1.0


class TestDeterminism:
    """NFR-6: identical inputs must produce identical numbers, every run."""

    def test_repeated_scoring_is_identical(self):
        runs = [
            score_answer("Jane SmithJohn Doe", ["John DoeJane Smith"], ["Q1", "Q2"], ["Q2", "Q3"])
            for _ in range(10)
        ]
        assert all(run == runs[0] for run in runs)
