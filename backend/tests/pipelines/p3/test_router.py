"""Tests for Group 1: Necessity router.

Verification Plan Group 1:
- test_routing_lookup_direct
- test_routing_count_scoped
- test_routing_traverse_loops
"""

from __future__ import annotations

import pytest

from ogr.pipelines.p3_agentic.intent import Anchor, AnchorConstraint, IntentSchema
from ogr.pipelines.p3_agentic.router import is_fully_specified, route


def _make_intent(
    operation: str,
    title: str = None,
    event_id: str = None,
    sport: str = None,
    games: str = None,
    venue: str = None,
    target_field: str = None,
    constraints: list = None,
) -> IntentSchema:
    return IntentSchema(
        operation=operation,
        anchor=Anchor(
            title=title,
            event_id=event_id,
            sport=sport,
            games=games,
            venue=venue,
        ),
        target_field=target_field,
        constraints=[AnchorConstraint(**c) for c in (constraints or [])],
    )


class TestRoutingLookupDirect:
    """test_routing_lookup_direct: LOOKUP + fully-specified → lookup_direct (zero loop edges)."""

    def test_lookup_with_title_and_target_field(self):
        intent = _make_intent(
            "LOOKUP",
            title="Athletics at the 2016 Summer Olympics – Men's marathon",
            target_field="nations",
        )
        assert is_fully_specified(intent) is True
        assert route(intent) == "lookup_direct"

    def test_lookup_with_event_id_and_target_field(self):
        intent = _make_intent(
            "LOOKUP",
            event_id="Q123456",
            target_field="gold",
        )
        assert is_fully_specified(intent) is True
        assert route(intent) == "lookup_direct"

    def test_lookup_without_title_or_event_id_routes_to_loop(self):
        """LOOKUP with only sport+games is underspecified → routes to loop."""
        intent = _make_intent(
            "LOOKUP",
            sport="Sailing",
            games="2016-Summer",
            target_field="nations",
        )
        assert is_fully_specified(intent) is False
        assert route(intent) == "loop"

    def test_lookup_without_target_field_routes_to_loop(self):
        intent = _make_intent(
            "LOOKUP",
            title="Some event",
            target_field=None,
        )
        assert is_fully_specified(intent) is False
        assert route(intent) == "loop"

    def test_lookup_with_constraints_routes_to_loop(self):
        """DP-1 rule: constraints present → underspecified → loop."""
        intent = _make_intent(
            "LOOKUP",
            title="Athletics event",
            target_field="nations",
            constraints=[{"field": "competitors", "op": ">", "value": 50}],
        )
        assert is_fully_specified(intent) is False
        assert route(intent) == "loop"


class TestRoutingCountScoped:
    """test_routing_count_scoped: COUNT/ARGMAX → scoped_aggregate (one query, no loop)."""

    def test_count_routes_to_scoped_aggregate(self):
        intent = _make_intent("COUNT", sport="Sailing", games="2016-Summer", target_field="event_name")
        assert route(intent) == "scoped_aggregate"

    def test_argmax_routes_to_scoped_aggregate(self):
        intent = _make_intent("ARGMAX", sport="Swimming", games="2008-Summer", target_field="gold_noc")
        assert route(intent) == "scoped_aggregate"

    def test_count_with_constraints_still_scoped(self):
        """Constraints on COUNT are handled inside Q2, not by routing to loop."""
        intent = _make_intent(
            "COUNT",
            sport="Boxing",
            games="2004-Summer",
            target_field="competitors",
            constraints=[{"field": "competitors", "op": ">", "value": 10}],
        )
        assert route(intent) == "scoped_aggregate"


class TestRoutingTraverseLoops:
    """test_routing_traverse_loops: TRAVERSE → loop (agentic multi-step)."""

    def test_traverse_routes_to_loop(self):
        intent = _make_intent("TRAVERSE", title="Triathlon at the 2016 Summer Olympics")
        assert route(intent) == "loop"

    def test_traverse_with_no_anchor_routes_to_loop(self):
        intent = _make_intent("TRAVERSE")
        assert route(intent) == "loop"


class TestFullySpecifiedPredicate:
    """Unit tests for the DP-1 is_fully_specified predicate."""

    def test_title_and_target_is_fully_specified(self):
        intent = _make_intent("LOOKUP", title="Event X", target_field="gold")
        assert is_fully_specified(intent) is True

    def test_event_id_and_target_is_fully_specified(self):
        intent = _make_intent("LOOKUP", event_id="Q999", target_field="silver")
        assert is_fully_specified(intent) is True

    def test_no_direct_anchor_is_not_fully_specified(self):
        intent = _make_intent("LOOKUP", sport="Cycling", target_field="gold")
        assert is_fully_specified(intent) is False

    def test_no_target_field_is_not_fully_specified(self):
        intent = _make_intent("LOOKUP", title="Event X")
        assert is_fully_specified(intent) is False

    def test_constraints_present_is_not_fully_specified(self):
        intent = _make_intent(
            "LOOKUP",
            title="Event X",
            target_field="gold",
            constraints=[{"field": "nations", "op": ">", "value": 5}],
        )
        assert is_fully_specified(intent) is False
