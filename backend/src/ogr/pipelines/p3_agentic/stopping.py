"""Stopping criteria evaluator for P3 Agentic GraphRAG pipeline.

Source spec: APPLICATION-SPEC FR-7 · ARCHITECTURE-SPEC §3 · AD-3
Plan: implementation-plan-AGENT.md Group 4, DP-3 Option A

Stops the agentic loop on EITHER:
  - Evidence sufficiency (evidence evaluator returns is_sufficient=True)
  - Hard step budget exhaustion (step_count >= max_steps)
  - Hard token budget exhaustion (tokens_used >= max_tokens_per_query)
  - No further action available (all tools already tried, no new results)
  - Disambiguation required (anchor resolution returned candidates, no way to proceed)
  - Error state

DP-3 Option A — closed stop_reason vocabulary:
  sufficient_evidence      : Evidence evaluator confirmed sufficient coverage + groundedness
  step_budget_exhausted    : Reached max_steps (default 6, from run_config)
  token_budget_exhausted   : Reached max_tokens_per_query (default 20000)
  no_further_action_available : All tools tried, no additional evidence retrievable
  disambiguation_required  : Anchor unresolvable, candidates returned — surface to user
  error                    : Unrecoverable error in agent execution
  direct_route             : A one-query route (lookup/aggregation) answered without the
                             loop, so no evidence evaluation was run

AD-3: A fixed step count is NOT the stopping criterion — sufficiency is.
The budget exists as a safety valve, not as the primary stop signal.
"""

from __future__ import annotations

import logging
from typing import Literal

from ogr.pipelines.p3_agentic.evidence import EvidenceEvaluation

logger = logging.getLogger(__name__)

# Closed vocabulary per DP-3 Option A
StopReason = Literal[
    "sufficient_evidence",
    "step_budget_exhausted",
    "token_budget_exhausted",
    "no_further_action_available",
    "disambiguation_required",
    "error",
    "direct_route",
]

# Default budgets — sourced from RunConfig at runtime (env: RUN_MAX_STEPS, RUN_MAX_TOKENS_PER_QUERY)
DEFAULT_MAX_STEPS = 6
DEFAULT_MAX_TOKENS_PER_QUERY = 20_000

# Tools reachable inside the loop: one traversal tool per iteration, plus the
# two evidence-evaluator fallbacks (DP-2).
PRIMARY_LOOP_TOOLS = frozenset({"traversal", "multi_hop", "lookup"})
FALLBACK_TOOLS = frozenset({"similarity_search", "document_retrieval"})


def should_stop(
    evaluation: EvidenceEvaluation,
    step_count: int,
    tokens_used: int,
    tools_tried: list[str] | None = None,
    has_disambiguation_candidates: bool = False,
    has_error: bool = False,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_tokens: int = DEFAULT_MAX_TOKENS_PER_QUERY,
) -> tuple[bool, StopReason]:
    """Determine whether the agentic loop should stop.

    Returns:
        (stop: bool, reason: StopReason)
        If stop=False, the loop continues to the next tool agent.
    """
    # Error state — always stop
    if has_error:
        logger.debug("Stopping: error state")
        return True, "error"

    # Disambiguation — can't proceed without resolving the anchor
    if has_disambiguation_candidates:
        logger.debug("Stopping: disambiguation_required")
        return True, "disambiguation_required"

    # Evidence sufficiency — primary stopping condition (AD-3)
    if evaluation.is_sufficient:
        logger.debug("Stopping: sufficient_evidence after %d steps", step_count)
        return True, "sufficient_evidence"

    # Token budget — safety valve
    if tokens_used >= max_tokens:
        logger.warning("Stopping: token_budget_exhausted (%d >= %d)", tokens_used, max_tokens)
        return True, "token_budget_exhausted"

    # Step budget — safety valve
    if step_count >= max_steps:
        logger.warning("Stopping: step_budget_exhausted (%d >= %d)", step_count, max_steps)
        return True, "step_budget_exhausted"

    # No further action available. Only loop tools count: lookup and
    # aggregation route straight to generation and never enter the loop, so
    # requiring them here made this reason unreachable.
    tried = set(tools_tried or [])
    if tried & PRIMARY_LOOP_TOOLS and FALLBACK_TOOLS <= tried:
        logger.debug("Stopping: no_further_action_available — all loop tools exhausted")
        return True, "no_further_action_available"

    return False, "sufficient_evidence"  # unused when stop=False
