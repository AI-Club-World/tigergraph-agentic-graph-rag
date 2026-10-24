"""Temporal scope of a question (Round 2, ROUND2-DESIGN.md §3.1).

Which version of a fact the question asks for: the value as known at a
point in time, before or after one, between two, the latest, or the
original. Deterministic: a cue lexicon of general English plus the shared
date normaliser. No LLM (gate G3 allows an LLM fallback for ambiguous
cases, only if the dev split shows the rules fall short).

A time *of the fact* is not the time *of an entity*. "The Games held
immediately before 2016" moves along editions of an event (Round-1
TRAVERSE, PREV_EDITION); it does not ask for a fact as known before 2016.
So "before", "after", "since" and "between" scope a fact only next to a
revision cue ("revised", "reallocated", "reported", ...) or an explicit
"as of"; on their own they leave the scope `none`, and Round-1 behaviour is
unchanged. "On 6 August" is an event date and is never a scope.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

from ogr.common.dates import MONTH_MAP

__all__ = ["TemporalScope", "detect_temporal_scope"]

ScopeMode = Literal["none", "as_of", "before", "after", "between", "latest", "original"]


@dataclass(frozen=True)
class TemporalScope:
    mode: ScopeMode = "none"
    t1: str | None = None        # ISO date; the bound the mode uses
    t2: str | None = None        # ISO date; upper bound of `between`
    cue: str = ""                # the words that set the mode, for the trace
    ambiguous: bool = False      # a cue with no date it could resolve

    @property
    def scoped(self) -> bool:
        return self.mode != "none"

    def to_dict(self) -> dict:
        return asdict(self)


_MONTHS = "|".join(sorted(MONTH_MAP, key=len, reverse=True))
# "6 August 2018", "August 6, 2018", "August 2018", "2018-08-06", "2018".
_DATE = (
    rf"(?:\d{{1,2}}\s+(?:{_MONTHS})\.?\s+\d{{4}}"
    rf"|(?:{_MONTHS})\.?\s+\d{{1,2}},?\s+\d{{4}}"
    rf"|(?:{_MONTHS})\.?\s+\d{{4}}"
    rf"|\d{{4}}-\d{{2}}-\d{{2}}"
    rf"|(?<![\d-])(?:1[89]|20)\d\d(?![\d-]))"
)

_AS_OF = re.compile(
    rf"\b(as of|as at|at the time of|by the end of|known in|known by)\s+(?:the\s+)?({_DATE})", re.I
)
_BETWEEN = re.compile(rf"\bbetween\s+({_DATE})\s+and\s+({_DATE})", re.I)
_BEFORE = re.compile(rf"\b(before|prior to|until|up to)\s+({_DATE})", re.I)
_AFTER = re.compile(rf"\b(after|since|following)\s+({_DATE})", re.I)
_LATEST = re.compile(
    r"\b(latest|most recent(?:ly)?|currently|current|now|today|at present|presently|"
    r"as it stands|after (?:all|the) (?:revisions?|corrections?|updates?|reallocations?))\b",
    re.I,
)
_ORIGINAL = re.compile(
    r"\b(originally|initially|at first|first (?:awarded|reported|announced|recorded|listed)|"
    r"original(?:ly)? (?:winner|result|value|figure|record)|before (?:the|any) "
    r"(?:revisions?|corrections?|updates?|reallocations?|disqualifications?))\b",
    re.I,
)
# A fact that changed or was stated at a time: the cue that lets
# before/after/since/between scope the fact rather than an edition.
_REVISION = re.compile(
    r"\b(revis\w*|reallocat\w*|re-?award\w*|updat\w*|correct\w*|amend\w*|chang\w*|"
    r"stripp\w*|disqualif\w*|overturn\w*|report\w*|record(?:ed|s)|list(?:ed|s)|"
    r"official(?:ly)?|according to|stated|known|believed|held the)\b",
    re.I,
)


def _bounds(text: str) -> tuple[date, date] | None:
    """First and last day a date expression covers ("2018" -> Jan 1..Dec 31)."""
    text = text.strip().rstrip(",")
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        d = date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return d, d
    year = re.search(r"\d{4}", text)
    if not year:
        return None
    y = int(year.group(0))
    month = next(
        (num for name, num in sorted(MONTH_MAP.items(), key=lambda kv: -len(kv[0]))
         if re.search(rf"\b{name}\b", text, re.I)),
        None,
    )
    day = re.search(r"\b(\d{1,2})\b", re.sub(r"\d{4}", "", text))
    try:
        if month and day:
            d = date(y, month, int(day.group(1)))
            return d, d
        if month:
            return date(y, month, 1), date(y, month, calendar.monthrange(y, month)[1])
        return date(y, 1, 1), date(y, 12, 31)
    except ValueError:
        return None


def detect_temporal_scope(question: str) -> TemporalScope:
    """The temporal scope a question puts on the fact it asks for."""
    q = question or ""
    revision = _REVISION.search(q) is not None

    m = _AS_OF.search(q)
    if m and (b := _bounds(m.group(2))):
        return TemporalScope("as_of", b[1].isoformat(), cue=m.group(0))

    m = _ORIGINAL.search(q)
    if m:
        return TemporalScope("original", cue=m.group(0))

    if revision:
        m = _BETWEEN.search(q)
        if m and (b1 := _bounds(m.group(1))) and (b2 := _bounds(m.group(2))):
            return TemporalScope("between", b1[0].isoformat(), b2[1].isoformat(), cue=m.group(0))
        m = _BEFORE.search(q)
        if m and (b := _bounds(m.group(2))):
            # "before 2018": known on 31 Dec 2017 at the latest.
            return TemporalScope("before", b[0].isoformat(), cue=m.group(0))
        m = _AFTER.search(q)
        if m and (b := _bounds(m.group(2))):
            start = b[0] if m.group(1).lower() == "since" else b[1]
            return TemporalScope("after", start.isoformat(), cue=m.group(0))

    m = _LATEST.search(q)
    if m:
        return TemporalScope("latest", cue=m.group(0))

    # A scope word with nothing it could bind to ("as of when it was held").
    loose = re.search(r"\b(as of|at the time)\b", q, re.I)
    if loose:
        return TemporalScope("latest", cue=loose.group(0), ambiguous=True)
    return TemporalScope()
