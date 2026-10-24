"""Claims tool (Round 2, ROUND2-DESIGN.md §5): the facts the graph holds about
the question's subject, weighed by time, source and certainty.

Two steps, both deterministic and free of LLM calls:

- `probe_claims`: after entity linking, one Q6 call for the subject and the
  asked attribute. Claims *matter* when the question is time-scoped or the
  claims disagree (several values, or a hedged one). Otherwise the Round-1
  route is kept exactly as it was. The probe runs only on a graph that has
  the Round-2 types, so a Round-1 graph sees no extra query.
- `run_claims`: temporal scope, supersession and conflict resolution
  (reasoning/resolve.py). Each candidate value becomes one evidence row,
  labelled with its status, sources, time and support, chosen value first,
  so the shared answer prompt sees the agent's reasoning as context.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from ogr.datasets.base import ClaimRecord, normalize_predicate
from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors, lookup_named_event
from ogr.pipelines.p3_agentic.intent import IntentSchema
from ogr.pipelines.temporal import TemporalScope
from ogr.reasoning.relations import value_key
from ogr.reasoning.resolve import Resolution, Weights, resolve

logger = logging.getLogger(__name__)

__all__ = [
    "ClaimProbe", "MARGIN", "claims_enabled", "load_weights", "probe_claims", "run_claims",
]

# The chosen value's probability at or above which the claims are taken as
# settled without a corroborating search. A default; harness/fit.py may
# replace it with one fitted on the dev split.
MARGIN = 0.6
MAX_ROWS = 8
WEIGHTS_ENV = "OGR_ROUND2_WEIGHTS"


def claims_enabled(client: Any) -> bool:
    """Whether the graph has the Round-2 fact layer. Cached on the client;
    False for clients without the capability (mocks, stand-ins)."""
    check = getattr(client, "has_claims", None)
    try:
        return bool(check()) if callable(check) else False
    except Exception as e:  # noqa: BLE001 - a probe must never fail a run
        logger.warning("Claims capability check failed: %s", e)
        return False


def load_weights(path: str | None = None) -> Weights:
    """Weights fitted on the harness dev split (JSON of Weights fields), from
    `path` or $OGR_ROUND2_WEIGHTS; the defaults when neither is set."""
    path = path or os.environ.get(WEIGHTS_ENV)
    if not path:
        return Weights()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("Round-2 weights %s unreadable (%s); using defaults", path, e)
        return Weights()
    known = {f.name for f in fields(Weights)}
    return Weights(**{k: float(v) for k, v in data.items() if k in known})


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def claim_predicate(intent: IntentSchema | None) -> str:
    return normalize_predicate(getattr(intent, "target_field", "") or "")


def claim_subjects(client: Any, intent: IntentSchema, anchors: ResolvedAnchors) -> list[str]:
    """The ids claims about the question's subject are stored under: the
    named event (by id, by the id its sport/Games/title derive, else by
    Q1 on the title), and a generic entity of that name."""
    subjects: list[str] = []
    if anchors.event_id:
        subjects.append(anchors.event_id)
    elif anchors.derived_event_id:
        subjects.append(anchors.derived_event_id)
    elif anchors.title:
        rows = lookup_named_event(client, anchors, getattr(intent, "target_field", "") or "")
        subjects += [r["event_id"] for r in rows if r.get("event_id")]
    for name in (anchors.title, anchors.venue):
        if name:
            subjects.append(f"ent:{_slug(name)}")
    return list(dict.fromkeys(subjects))


@dataclass
class ClaimProbe:
    subjects: list[str] = field(default_factory=list)
    predicate: str = ""
    claims: list[ClaimRecord] = field(default_factory=list)
    relevant: bool = False
    reason: str = ""


def probe_claims(client: Any, intent: IntentSchema | None, anchors: ResolvedAnchors | None,
                 scope: TemporalScope) -> ClaimProbe:
    if intent is None or anchors is None or getattr(intent, "operation", "") in ("COUNT", "ARGMAX"):
        return ClaimProbe(reason="aggregation or no parse: Round-1 route")
    predicate = claim_predicate(intent)
    if not predicate:
        return ClaimProbe(reason="no attribute asked")
    subjects = claim_subjects(client, intent, anchors)
    if not subjects:
        return ClaimProbe(predicate=predicate, reason="no subject")
    claims = client.claims(subjects, predicate)
    probe = ClaimProbe(subjects, predicate, claims)
    if not claims:
        probe.reason = "no claims"
    elif scope.scoped:
        probe.relevant, probe.reason = True, f"time-scoped ({scope.mode})"
    elif len({value_key(c) for c in claims}) > 1:
        probe.relevant, probe.reason = True, f"{len({value_key(c) for c in claims})} values"
    elif any(c.hedged for c in claims):
        probe.relevant, probe.reason = True, "hedged"
    else:
        probe.reason = "one firm value: Round-1 route"
    return probe


def _row(resolution: Resolution, status: str, value: str, claims: list[ClaimRecord],
         **extra: Any) -> dict[str, Any]:
    first = min(claims, key=lambda c: (c.observed_at or "", c.claim_id))
    observed = sorted({c.observed_at for c in claims if c.observed_at})
    hedges = sorted({t for c in claims for t in c.hedge_terms})
    return {
        "subject": first.subject_name or resolution.subject_id,
        "attribute": resolution.predicate,
        "value": value,
        "status": status,
        **extra,
        "sources": "; ".join(sorted({c.source_id.removeprefix("src:") for c in claims if c.source_id})),
        "stated": ", ".join(observed) if observed else "undated",
        "valid_from": first.valid_from or "",
        "hedged": ", ".join(hedges),
        "doc_id": first.doc_id,
        "source": "claims",
    }


def run_claims(probe: ClaimProbe, scope: TemporalScope, reliability: dict[str, float],
               weights: Weights | None = None) -> tuple[AgentResult, Resolution]:
    t0 = time.perf_counter()
    resolution = resolve(probe.claims, scope, reliability, weights)
    rows: list[dict[str, Any]] = []
    if resolution.chosen:
        c = resolution.chosen
        rows.append(_row(resolution, "chosen by conflict resolution", c.value, c.claims,
                         support=f"{c.probability:.2f} of the weight"))
        for alt in resolution.alternatives:
            rows.append(_row(resolution, "conflicting value, less support", alt.value, alt.claims,
                             support=f"{alt.probability:.2f} of the weight"))
        for old in resolution.superseded:
            rows.append(_row(resolution, "superseded by a later statement", old.value_text, [old]))
        for out in resolution.out_of_scope[:2]:
            rows.append(_row(resolution, f"outside the asked time ({scope.mode})", out.value_text, [out]))
    rows = rows[:MAX_ROWS]
    result = AgentResult(
        evidence=rows,
        chunks_returned=len(rows),
        citations_count=len(rows),
        latency_ms=(time.perf_counter() - t0) * 1000.0,
        notes=f"Q6 claims on {', '.join(probe.subjects)} [{probe.predicate}]: {resolution.notes}; "
              f"confidence {resolution.confidence:.2f}",
    )
    return result, resolution
