"""Supersession and contradiction between claims (ROUND2-DESIGN.md §2).

Deterministic, built at ingest from the claims alone, and recorded with the
reason, so every relation the agent relies on can be inspected.

- SUPERSEDES(new -> old): same subject and predicate, different values, and
  `new` is later *and* either says it revises an earlier statement
  (`revision`) or comes from the same source. A hedged statement never
  supersedes a firm one. "Later" compares observed
  times, then validity starts. A claim with no observed time (an
  encyclopedia page) is earlier than a dated revision.
- CONTRADICTS(a <-> b): same subject and predicate, different values,
  overlapping validity, and no supersession either way.
- The same value from several sources is corroboration, not a relation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from ogr.common.names import normalized_name_set
from ogr.datasets.base import ClaimRecord

__all__ = ["Relation", "build_relations", "group_claims", "value_key"]


@dataclass(frozen=True)
class Relation:
    kind: str           # "SUPERSEDES" | "CONTRADICTS"
    src: str            # claim_id (the newer one, for SUPERSEDES)
    dst: str            # claim_id
    reason: str


def value_key(claim: ClaimRecord) -> object:
    """What makes two values the same: the number, else the normalised
    name set the scorer compares answers by."""
    if claim.value_num is not None:
        return round(float(claim.value_num), 6)
    return normalized_name_set(claim.value_text) or claim.value_text.strip().lower()


def group_claims(claims: Iterable[ClaimRecord]) -> dict[tuple[str, str], list[ClaimRecord]]:
    groups: dict[tuple[str, str], list[ClaimRecord]] = defaultdict(list)
    for claim in claims:
        groups[(claim.subject_id, claim.predicate)].append(claim)
    return dict(groups)


def _later(new: ClaimRecord, old: ClaimRecord) -> str | None:
    """Why `new` is later than `old`, or None when it is not."""
    if new.observed_at and (not old.observed_at or new.observed_at > old.observed_at):
        return "observed later" if old.observed_at else "dated; the other is undated"
    same_time = new.observed_at == old.observed_at
    if same_time and new.valid_from and old.valid_from and new.valid_from > old.valid_from:
        return "valid from later"
    return None


def _overlap(a: ClaimRecord, b: ClaimRecord) -> bool:
    lo = max(a.valid_from or "", b.valid_from or "")
    hi = min(a.valid_to or "9999-12-31", b.valid_to or "9999-12-31")
    return lo <= hi


def build_relations(claims: Iterable[ClaimRecord]) -> list[Relation]:
    relations: list[Relation] = []
    for (_subject, _predicate), group in sorted(group_claims(claims).items()):
        group = sorted(group, key=lambda c: c.claim_id)
        superseded_pairs: set[frozenset[str]] = set()
        for new in group:
            for old in group:
                if new is old or value_key(new) == value_key(old):
                    continue
                later = _later(new, old)
                # A hedged statement ("reportedly to be upgraded") does not
                # override a firm one, whether or not it claims to revise it.
                if not later or (new.hedged and not old.hedged):
                    continue
                if new.revision:
                    reason = f"revision, {later}"
                elif new.source_id and new.source_id == old.source_id:
                    reason = f"same source, {later}"
                else:
                    continue
                relations.append(Relation("SUPERSEDES", new.claim_id, old.claim_id, reason))
                superseded_pairs.add(frozenset((new.claim_id, old.claim_id)))
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if value_key(a) == value_key(b) or frozenset((a.claim_id, b.claim_id)) in superseded_pairs:
                    continue
                if _overlap(a, b):
                    relations.append(Relation(
                        "CONTRADICTS", a.claim_id, b.claim_id, "different values, overlapping validity"
                    ))
    return relations
