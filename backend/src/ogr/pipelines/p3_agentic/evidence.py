"""Evidence evaluator for P3 Agentic GraphRAG pipeline.

Source spec: ARCHITECTURE-SPEC §3, §4 · APPLICATION-SPEC FR-6
Plan: implementation-plan-AGENT.md Group 4, DP-4 Option A

Two-stage evaluation per DP-4 Option A:
  Stage 1 (deterministic): Scope-coverage gate — did retrieval cover the
           anchor's required scope? Cheap and fully reproducible.
  Stage 2 (LLM): One groundedness check — does the evidence support the
           claim being made? Clearly labelled as an LLM call. For prose-only
           evidence it runs only after a deterministic token-overlap
           pre-check passes: chunks sharing fewer than two content words with
           the question fail groundedness without an LLM call
           (deterministic-first). Structured graph results (traversal,
           multi-hop, aggregation) always go to the LLM — an exact graph value
           such as a medal-winning nation need not share words with the
           question.

NFR-6 note: The LLM groundedness call is a RETRIEVAL DECISION, not a score.
The scoring loop (EM/F1) remains fully deterministic. This is not a contradiction
with NFR-6; it is a distinction that the README should state plainly.

Fallback triggers (DP-2 Option A):
  - scope_coverage_fail → similarity_search (Q5 expansion)
  - groundedness_fail   → document_retrieval (HAS_CHUNK prose)
  - empty_anchor        → document_retrieval (HAS_CHUNK prose)

parse_confidence surfacing: Q2/Q3 results carry an excluded_count in notes.
The evaluator surfaces this in its own notes field — 'the system tells you
what it could not parse' is a demonstrable property.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

logger = logging.getLogger(__name__)

FallbackTrigger = Literal[
    "scope_coverage_fail",
    "groundedness_fail",
    "empty_anchor",
    "none",
]


# Evidence produced by exact graph queries rather than retrieved prose.
STRUCTURED_SOURCES = frozenset({"graph_traversal", "multi_hop", "aggregation_count", "aggregation_argmax"})


@dataclass
class EvidenceEvaluation:
    """Result of evidence evaluation."""
    is_sufficient: bool
    scope_coverage_pass: bool
    groundedness_pass: bool
    fallback_trigger: FallbackTrigger
    notes: str = ""
    # Tokens spent by the groundedness call. The loop's only LLM call, so
    # without this the token budget can never arm (DP-3, DP-5).
    tokens_input: int = 0
    tokens_output: int = 0


def evaluate_evidence(
    evidence: list[dict[str, Any]],
    intent_operation: str,
    anchors: Any,         # ResolvedAnchors
    model: Any | None = None,   # LLM for groundedness check
    question: str = "",
    reports_usage: str = "auto",
) -> EvidenceEvaluation:
    """Evaluate whether the retrieved evidence is sufficient.

    Args:
        evidence: List of evidence dicts from tool agents.
        intent_operation: The parsed operation (LOOKUP, COUNT, ARGMAX, TRAVERSE).
        anchors: ResolvedAnchors for scope checking.
        model: LLM model for groundedness (optional; skipped if None).
        question: Original question for groundedness prompt.
    """
    # Stage 1: Deterministic scope-coverage gate
    scope_pass, scope_notes = _check_scope_coverage(evidence, intent_operation, anchors)

    if not scope_pass:
        return EvidenceEvaluation(
            is_sufficient=False,
            scope_coverage_pass=False,
            groundedness_pass=False,
            fallback_trigger="scope_coverage_fail",
            notes=scope_notes,
        )

    if not evidence:
        return EvidenceEvaluation(
            is_sufficient=False,
            scope_coverage_pass=False,
            groundedness_pass=False,
            fallback_trigger="empty_anchor",
            notes="No evidence retrieved",
        )

    # Stage 2: deterministic overlap pre-check (DP-4 Option B) for prose-only
    # evidence, then the LLM groundedness check (DP-4 Option A). A failed
    # pre-check already decides the fallback, so the LLM call is skipped.
    tokens_in = tokens_out = 0
    structured = any(e.get("source") in STRUCTURED_SOURCES for e in evidence)
    groundedness_pass, ground_notes = _check_groundedness_deterministic(evidence, question)
    if (groundedness_pass or structured) and model is not None and question:
        groundedness_pass, ground_notes, tokens_in, tokens_out = _check_groundedness_llm(
            evidence, question, model, reports_usage
        )
    elif model is not None:
        ground_notes += " (LLM check skipped)"

    if not groundedness_pass:
        return EvidenceEvaluation(
            is_sufficient=False,
            scope_coverage_pass=True,
            groundedness_pass=False,
            fallback_trigger="groundedness_fail",
            notes=ground_notes,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
        )

    # Collect parse_confidence notes from Q2/Q3 evidence
    excluded_notes = _collect_parse_confidence_notes(evidence)
    all_notes = "; ".join(filter(None, [scope_notes, ground_notes, excluded_notes]))

    return EvidenceEvaluation(
        is_sufficient=True,
        scope_coverage_pass=True,
        groundedness_pass=True,
        fallback_trigger="none",
        notes=all_notes,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
    )


def _check_scope_coverage(
    evidence: list[dict[str, Any]],
    operation: str,
    anchors: Any,
) -> tuple[bool, str]:
    """Deterministic scope-coverage gate."""
    if not evidence:
        return False, "Empty evidence set"

    # For COUNT/ARGMAX: need at least one aggregation result
    if operation in ("COUNT", "ARGMAX"):
        agg_results = [e for e in evidence if e.get("source") in ("aggregation_count", "aggregation_argmax")]
        if agg_results:
            return True, f"scope: {len(agg_results)} aggregation result(s)"
        # Non-aggregation evidence for an aggregation question = scope fail
        return False, "COUNT/ARGMAX operation but no aggregation results in evidence"

    # For LOOKUP: need at least one evidence item
    if operation == "LOOKUP":
        if len(evidence) >= 1:
            return True, f"scope: {len(evidence)} lookup result(s)"
        return False, "LOOKUP: no results"

    # For TRAVERSE: need at least one traversal or multi-hop result
    if operation == "TRAVERSE":
        traversal = [e for e in evidence if e.get("source") in ("graph_traversal", "multi_hop")]
        if traversal:
            return True, f"scope: {len(traversal)} traversal result(s)"
        # Similarity/doc fallback may still provide coverage
        if evidence:
            return True, f"scope: {len(evidence)} fallback result(s)"
        return False, "TRAVERSE: no traversal or fallback results"

    # Default: any evidence passes
    return len(evidence) > 0, f"scope: {len(evidence)} evidence item(s)"


def _check_groundedness_llm(
    evidence: list[dict[str, Any]],
    question: str,
    model: Any,
    reports_usage: str = "auto",
) -> tuple[bool, str, int, int]:
    """LLM groundedness check — labelled as LLM call (DP-4 Option A).

    Returns (passed, notes, tokens_input, tokens_output).
    """
    from ogr.common.llm import LLMRateLimitError, _response_text, invoke_and_count

    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        from langchain.schema import HumanMessage, SystemMessage

    # Compact evidence text for the prompt
    evidence_text = "\n".join(
        e.get("text", e.get("event_name", str(e.get("value", ""))))[:200]
        for e in evidence[:5]
    )
    prompt = (
        f"Evidence:\n{evidence_text}\n\n"
        f"Question: {question}\n\n"
        "Does the evidence above contain information sufficient to answer the question? "
        "Reply with a single word: YES or NO."
    )
    try:
        response, tokens, _source, _latency = invoke_and_count(model, [
            SystemMessage(content="You are a groundedness evaluator. Answer only YES or NO."),
            HumanMessage(content=prompt),
        ], reports_usage=reports_usage)
        # Claude and Gemini may return content as a list of blocks.
        raw = _response_text(response).strip().upper()
        passed = raw.startswith("YES")
        return (
            passed,
            f"LLM groundedness: {'pass' if passed else 'fail'}",
            tokens.input,
            tokens.output,
        )
    except LLMRateLimitError:
        raise  # DP-3: no silent deterministic substitute for a rate-limited model
    except Exception as e:
        logger.warning("Groundedness LLM call failed: %s; falling back to deterministic", e)
        passed, notes = _check_groundedness_deterministic(evidence, question)
        return passed, notes, 0, 0


def _check_groundedness_deterministic(
    evidence: list[dict[str, Any]],
    question: str,
) -> tuple[bool, str]:
    """Deterministic groundedness: minimal token overlap check (DP-4 Option B baseline)."""
    if not evidence or not question:
        return False, "deterministic groundedness: no evidence or question"
    q_tokens = set(re.findall(r"\w+", question.lower()))
    for e in evidence:
        text = e.get("text", e.get("event_name", str(e.get("value", ""))))
        e_tokens = set(re.findall(r"\w+", text.lower()))
        overlap = q_tokens & e_tokens - {"the", "a", "an", "of", "in", "at", "is", "was", "did"}
        if len(overlap) >= 2:
            return True, "deterministic groundedness: token overlap pass"
    return False, "deterministic groundedness: insufficient token overlap"


def _collect_parse_confidence_notes(evidence: list[dict[str, Any]]) -> str:
    """Surface parse_confidence exclusion counts from Q2/Q3 evidence."""
    total_excluded = sum(
        int(e.get("excluded_count", 0)) for e in evidence
        if "excluded_count" in e
    )
    if total_excluded > 0:
        return f"parse_confidence_excluded={total_excluded}"
    return ""
