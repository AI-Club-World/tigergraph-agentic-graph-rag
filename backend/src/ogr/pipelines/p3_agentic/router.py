"""Necessity router for P3 Agentic GraphRAG pipeline.

Source spec: ARCHITECTURE-SPEC §5 · APPLICATION-SPEC FR-11 · AD-5

Routes parsed intent to one of three paths based on the DP-1 fully-specified rule:
  - lookup_direct    : LOOKUP with fully-specified anchor → Q1 direct, NO loop
  - scoped_aggregate : COUNT or ARGMAX → Q2/Q3, one query
  - loop             : TRAVERSE or underspecified anchor → multi-step agentic loop

FULLY-SPECIFIED RULE (DP-1 Option A, TECHNICAL-SPEC §7):
  fully_specified ⇔ (anchor.title OR anchor.event_id non-null)
                  AND target_field non-null
                  AND constraints empty

This is a deterministic, one-line rule — no trained classifier, no qtype read,
no question-template regex. NFR-7 compliant by construction.
"""

from __future__ import annotations

import logging
from typing import Literal

from ogr.pipelines.p3_agentic.intent import IntentSchema

logger = logging.getLogger(__name__)

RouteDecision = Literal["lookup_direct", "scoped_aggregate", "loop"]
LoopTool = Literal["lookup", "multi_hop", "venue", "traversal"]


def is_fully_specified(intent: IntentSchema) -> bool:
    """Deterministic fully-specified predicate per DP-1 Option A.

    fully-specified ⇔ (anchor.title or anchor.event_id non-null)
                     AND target_field non-null
                     AND constraints empty
    """
    has_direct_anchor = bool(intent.anchor.title) or bool(intent.anchor.event_id)
    has_target = intent.target_field is not None and intent.target_field.strip() != ""
    has_no_constraints = len(intent.constraints) == 0
    return has_direct_anchor and has_target and has_no_constraints


def route(intent: IntentSchema) -> RouteDecision:
    """Map parsed intent to a routing decision.

    Rules per ARCHITECTURE-SPEC §5:
      LOOKUP + fully_specified  → lookup_direct   (Q1, zero loop edges)
      COUNT / ARGMAX            → scoped_aggregate (Q2/Q3, one query)
      TRAVERSE / underspecified → loop            (agentic multi-step)
    """
    if intent.operation == "LOOKUP":
        if is_fully_specified(intent):
            logger.debug("Router: LOOKUP + fully-specified → lookup_direct")
            return "lookup_direct"
        else:
            logger.debug("Router: LOOKUP + underspecified anchor → loop")
            return "loop"

    if intent.operation in ("COUNT", "ARGMAX"):
        logger.debug("Router: %s → scoped_aggregate", intent.operation)
        return "scoped_aggregate"

    # TRAVERSE or any unrecognised operation → loop
    logger.debug("Router: %s → loop", intent.operation)
    return "loop"


# Attributes one event carries: "how many nations competed in <event>" reads
# one of these; it counts nothing. (`nation` is the parser's singular.)
EVENT_COUNT_ATTRIBUTES = frozenset({"nations", "nation", "competitors", "competitor"})


def refine_route(decision: RouteDecision, intent: IntentSchema, anchors) -> RouteDecision:
    """After entity linking: a COUNT that names one specific event (sport +
    Games + event, so its event_id is derivable) and asks for an attribute
    that event carries is a lookup of that attribute, not a count of events
    (r1: "How many nations competed in Judo at the 2016 Summer Olympics –
    Women's 57 kg?" counted 14 events; the answer is the event's 23 nations).
    Deterministic, from the parsed intent and resolved anchors only. Shared
    by P2 and P3 so the ablation stays one variable."""
    if (
        decision == "scoped_aggregate"
        and intent.operation == "COUNT"
        and not intent.constraints
        and (intent.target_field or "").strip().lower() in EVENT_COUNT_ATTRIBUTES
        and (getattr(anchors, "event_id", None) or getattr(anchors, "derived_event_id", None))
    ):
        logger.debug("Router: COUNT of one named event's attribute → lookup_direct")
        return "lookup_direct"
    return decision


def first_loop_tool(intent: IntentSchema, anchors) -> LoopTool:
    """The tool a `loop` route starts with — shared by P3 (every iteration)
    and P2 (its single step), so the two differ only by the loop.

      named event, not TRAVERSE -> lookup     (Q1 on that event; Q4 would
                                               answer from its previous edition)
      named event, TRAVERSE     -> multi_hop  (resolve event, Q4, Q1)
      venue only                -> venue      (Q4 HELD_AT; a venue matches no event name)
      otherwise                 -> traversal  (Q4 on whatever anchor exists)
    """
    if getattr(anchors, "title", None) or getattr(anchors, "event_id", None):
        return "multi_hop" if intent.operation == "TRAVERSE" else "lookup"
    if getattr(anchors, "venue", None):
        return "venue"
    return "traversal"


def loop_tool_candidates(intent: IntentSchema, anchors) -> list[LoopTool]:
    """Every loop tool that applies to these anchors, first choice first.
    The loop runs the first one not yet tried, so a pass that found too
    little moves on to another retrieval method instead of repeating itself."""
    first = first_loop_tool(intent, anchors)
    options: list[LoopTool] = [first]
    if getattr(anchors, "title", None) or getattr(anchors, "event_id", None):
        options += ["lookup", "multi_hop"]
    if getattr(anchors, "venue", None):
        options.append("venue")
    options.append("traversal")
    return list(dict.fromkeys(options))
