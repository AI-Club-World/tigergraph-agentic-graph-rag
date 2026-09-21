"""Strategy-Change Detector for P3 Agentic GraphRAG pipeline.

Source spec: APPLICATION-SPEC FR-6 · ARCHITECTURE-SPEC §3
Plan: implementation-plan-AGENT.md Group 4

Compares the executed path_taken list against the router's recorded
initial routing decision (route_initial). Sets strategy_change=True
on any step that deviates from the initial route.

The strategy_changed boolean on the final PipelineRecord is DERIVED
from path_taken vs route_initial — not set imperatively in five places.

This is what makes the Strategy-Change Detector's output verifiable:
  - route_initial is recorded once when the necessity router fires
  - path_taken is an append-only list of tool names executed
  - deviation = any path_taken entry that is not consistent with route_initial
"""

from __future__ import annotations

from typing import List, Optional


# Map route decisions to expected tool categories
ROUTE_TO_EXPECTED_TOOLS = {
    "lookup_direct": {"lookup"},
    "scoped_aggregate": {"aggregation"},
    "loop": {"traversal", "similarity_search", "document_retrieval", "multi_hop", "aggregation"},
}


def detect_strategy_change(
    route_initial: str,
    path_taken: List[str],
) -> tuple[bool, Optional[str]]:
    """Determine whether the executed path deviated from the initial route.

    Args:
        route_initial: The initial routing decision ('lookup_direct', 'scoped_aggregate', 'loop').
        path_taken: List of tool names actually executed.

    Returns:
        (strategy_changed: bool, first_deviation: Optional[str])
        strategy_changed=True if any step was outside the expected tool set.
    """
    if not path_taken:
        return False, None

    expected = ROUTE_TO_EXPECTED_TOOLS.get(route_initial, set())
    for step in path_taken:
        if step not in expected:
            return True, step

    return False, None


def annotate_steps_with_strategy_change(
    route_initial: str,
    path_taken: List[str],
) -> List[bool]:
    """Return a parallel list of strategy_change booleans per step.

    Args:
        route_initial: Initial route decision.
        path_taken: Ordered list of tool names used.

    Returns:
        List[bool] of same length as path_taken — True for the first deviating step.
    """
    expected = ROUTE_TO_EXPECTED_TOOLS.get(route_initial, set())
    result = []
    changed = False
    for step in path_taken:
        if not changed and step not in expected:
            changed = True
            result.append(True)
        else:
            result.append(False)
    return result
