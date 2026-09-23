"""Tests for Group 4: Evidence evaluator, stopping criteria, strategy detection.

Verification Plan Group 4:
- test_stop_reason_in_closed_vocabulary
- test_budget_exhaustion_stops_loop
- test_strategy_change_flagged_on_refallback
"""

from __future__ import annotations

import pytest

from ogr.pipelines.p3_agentic.evidence import EvidenceEvaluation, evaluate_evidence
from ogr.pipelines.p3_agentic.stopping import (
    StopReason,
    should_stop,
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_TOKENS_PER_QUERY,
)
from ogr.pipelines.p3_agentic.strategy import (
    annotate_steps_with_strategy_change,
    detect_strategy_change,
)

# Closed stop_reason vocabulary per DP-3 Option A
CLOSED_STOP_REASONS = {
    "sufficient_evidence",
    "step_budget_exhausted",
    "token_budget_exhausted",
    "no_further_action_available",
    "disambiguation_required",
    "error",
}


def _sufficient_eval() -> EvidenceEvaluation:
    return EvidenceEvaluation(
        is_sufficient=True,
        scope_coverage_pass=True,
        groundedness_pass=True,
        fallback_trigger="none",
        notes="test: sufficient",
    )


def _insufficient_eval(trigger="scope_coverage_fail") -> EvidenceEvaluation:
    return EvidenceEvaluation(
        is_sufficient=False,
        scope_coverage_pass=False,
        groundedness_pass=False,
        fallback_trigger=trigger,
        notes="test: insufficient",
    )


class TestStopReasonInClosedVocabulary:
    """test_stop_reason_in_closed_vocabulary"""

    def test_sufficient_evidence_returns_closed_vocabulary_reason(self):
        stop, reason = should_stop(
            evaluation=_sufficient_eval(),
            step_count=2,
            tokens_used=1000,
        )
        assert stop is True
        assert reason in CLOSED_STOP_REASONS
        assert reason == "sufficient_evidence"

    def test_error_state_returns_error_reason(self):
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=1,
            tokens_used=100,
            has_error=True,
        )
        assert stop is True
        assert reason == "error"
        assert reason in CLOSED_STOP_REASONS

    def test_disambiguation_reason_in_vocabulary(self):
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=1,
            tokens_used=100,
            has_disambiguation_candidates=True,
        )
        assert stop is True
        assert reason == "disambiguation_required"
        assert reason in CLOSED_STOP_REASONS

    def test_no_further_action_in_vocabulary(self):
        all_tools_tried = [
            "lookup", "aggregation", "traversal",
            "similarity_search", "document_retrieval", "multi_hop",
        ]
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=3,
            tokens_used=1000,
            tools_tried=all_tools_tried,
        )
        assert stop is True
        assert reason == "no_further_action_available"
        assert reason in CLOSED_STOP_REASONS

    def test_no_further_action_reachable_with_loop_tools_only(self):
        """lookup/aggregation never enter the loop, so the reason must fire on
        the tools a loop run can actually try."""
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=3,
            tokens_used=1000,
            tools_tried=["traversal", "similarity_search", "document_retrieval"],
        )
        assert stop is True
        assert reason == "no_further_action_available"

    def test_continue_when_not_stopping(self):
        """Loop continues when nothing triggers a stop."""
        stop, _ = should_stop(
            evaluation=_insufficient_eval(),
            step_count=1,
            tokens_used=100,
            tools_tried=["traversal"],
        )
        assert stop is False


class TestBudgetExhaustion:
    """test_budget_exhaustion_stops_loop"""

    def test_step_budget_exhausted(self):
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=DEFAULT_MAX_STEPS,  # at the limit
            tokens_used=100,
        )
        assert stop is True
        assert reason == "step_budget_exhausted"

    def test_step_budget_not_exhausted_at_one_below_limit(self):
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=DEFAULT_MAX_STEPS - 1,
            tokens_used=100,
            tools_tried=["traversal"],
        )
        assert stop is False

    def test_token_budget_exhausted(self):
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=1,
            tokens_used=DEFAULT_MAX_TOKENS_PER_QUERY,  # at the limit
        )
        assert stop is True
        assert reason == "token_budget_exhausted"

    def test_token_budget_not_exhausted_just_below(self):
        stop, _ = should_stop(
            evaluation=_insufficient_eval(),
            step_count=1,
            tokens_used=DEFAULT_MAX_TOKENS_PER_QUERY - 1,
            tools_tried=["traversal"],
        )
        assert stop is False

    def test_custom_budget_from_run_config(self):
        """run_config values override defaults."""
        stop, reason = should_stop(
            evaluation=_insufficient_eval(),
            step_count=3,
            tokens_used=100,
            max_steps=3,  # custom lower limit
            max_tokens=50000,
        )
        assert stop is True
        assert reason == "step_budget_exhausted"

    def test_default_max_steps_is_6(self):
        """DP-3 Option A specifies max_steps=6."""
        assert DEFAULT_MAX_STEPS == 6

    def test_default_max_tokens_is_20000(self):
        """DP-3 Option A specifies max_tokens_per_query=20000."""
        assert DEFAULT_MAX_TOKENS_PER_QUERY == 20_000


class TestStrategyChangeDetection:
    """test_strategy_change_flagged_on_refallback"""

    def test_strategy_change_flagged_on_similarity_fallback(self):
        """Similarity search is not in lookup_direct's expected set → strategy change."""
        changed, first_deviation = detect_strategy_change(
            route_initial="lookup_direct",
            path_taken=["lookup", "similarity_search"],
        )
        assert changed is True
        assert first_deviation == "similarity_search"

    def test_strategy_change_flagged_on_doc_retrieval_fallback(self):
        """Document retrieval fallback in a scoped_aggregate run → strategy change."""
        changed, first = detect_strategy_change(
            route_initial="scoped_aggregate",
            path_taken=["aggregation", "document_retrieval"],
        )
        assert changed is True
        assert first == "document_retrieval"

    def test_no_strategy_change_when_path_matches_route(self):
        changed, _ = detect_strategy_change(
            route_initial="lookup_direct",
            path_taken=["lookup"],
        )
        assert changed is False

    def test_no_strategy_change_for_loop_traversal(self):
        changed, _ = detect_strategy_change(
            route_initial="loop",
            path_taken=["traversal", "multi_hop"],
        )
        assert changed is False

    def test_annotate_steps_parallel_list(self):
        """annotate_steps_with_strategy_change returns parallel boolean list."""
        result = annotate_steps_with_strategy_change(
            route_initial="loop",
            path_taken=["traversal", "similarity_search", "document_retrieval"],
        )
        assert len(result) == 3
        assert result[0] is False       # traversal is in loop's expected set
        assert result[1] is False       # similarity_search is also in loop's set
        assert result[2] is False       # document_retrieval is in loop's set

    def test_strategy_change_on_first_deviation_only(self):
        """strategy_change=True only on the FIRST deviating step."""
        result = annotate_steps_with_strategy_change(
            route_initial="lookup_direct",
            path_taken=["lookup", "similarity_search", "document_retrieval"],
        )
        assert result[0] is False     # lookup is expected
        assert result[1] is True      # first deviation
        assert result[2] is False     # subsequent deviations not re-flagged


class TestEvidenceEvaluation:
    def test_empty_evidence_is_insufficient(self):
        from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
        result = evaluate_evidence(
            evidence=[],
            intent_operation="COUNT",
            anchors=ResolvedAnchors(),
            model=None,
            question="How many events?",
        )
        assert result.is_sufficient is False
        assert result.fallback_trigger in ("scope_coverage_fail", "empty_anchor")

    def test_aggregation_evidence_passes_scope(self):
        from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors
        result = evaluate_evidence(
            evidence=[{"count": 26, "source": "aggregation_count"}],
            intent_operation="COUNT",
            anchors=ResolvedAnchors(),
            model=None,
            question="How many events?",
        )
        assert result.scope_coverage_pass is True
