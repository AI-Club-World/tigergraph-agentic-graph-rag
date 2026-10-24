"""Hedge detection: a statement qualified as uncertain (ROUND2-DESIGN.md §2).

A general English lexicon, versioned here, never derived from questions or
from the harness templates. A hedged claim keeps its value but gets a lower
claim confidence (reasoning/confidence.py)."""

from __future__ import annotations

import re

__all__ = ["HEDGE_LEXICON_VERSION", "hedge_terms", "revision_terms"]

HEDGE_LEXICON_VERSION = 1

_HEDGES = re.compile(
    r"\b("
    r"reportedly|allegedly|purportedly|supposedly|apparently|seemingly|"
    r"(?:is|are|was|were) (?:reported|believed|thought|said|claimed|understood|rumou?red) to|"
    r"it is (?:claimed|believed|thought|said|reported|understood)|"
    r"(?:un|not )(?:confirmed|verified|official)|unconfirmed|unverified|unofficial|"
    r"provisional(?:ly)?|preliminary|tentative(?:ly)?|pending (?:review|confirmation|appeal)|"
    r"disputed|contested|under (?:review|investigation|appeal)|"
    r"estimated|an estimate|approximately|roughly|(?:around|about|some|nearly|almost)(?=\s+\d)|"
    r"(?:may|might|could) (?:have|be)|possibly|probably|likely|perhaps|"
    r"sources (?:suggest|indicate|differ)|according to (?:some|unofficial|early|initial)"
    r")\b",
    re.IGNORECASE,
)


def hedge_terms(text: str | None) -> list[str]:
    """The hedge expressions in `text`, lower-cased, in order, without repeats."""
    seen: list[str] = []
    for m in _HEDGES.finditer(text or ""):
        term = " ".join(m.group(1).lower().split())
        if term not in seen:
            seen.append(term)
    return seen


_REVISION = re.compile(
    r"\b(correct(?:ed|ion|s)|revis(?:ed|ion|es)|reallocat(?:ed|ion|es)|re-?award(?:ed|s)?|"
    r"upgraded to|stripped|amend(?:ed|ment|s)|updat(?:ed|es)|overturn(?:ed|s)|rectif(?:ied|ies)|"
    r"replac(?:es|ed|ing) (?:the )?(?:earlier|previous|original)|supersed(?:es|ed|ing)|retroactive(?:ly)?)\b",
    re.IGNORECASE,
)


def revision_terms(text: str | None) -> list[str]:
    """Words saying a statement revises an earlier one (a correction,
    reallocation, update): one condition for SUPERSEDES."""
    seen: list[str] = []
    for m in _REVISION.finditer(text or ""):
        term = m.group(1).lower()
        if term not in seen:
            seen.append(term)
    return seen
