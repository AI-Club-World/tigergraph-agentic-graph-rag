"""Dataset adapter contract (ROUND2-DESIGN.md §1).

An adapter turns one dataset's files into `SourceRecord`s (documents with
provenance) and `ClaimRecord`s (statements with time, provenance and
confidence). Everything downstream (claim loading, conflict resolution,
the agent's claim tools) reads only these two types, so a new dataset needs
a new adapter and nothing else.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from ogr.common.dates import normalize_date

__all__ = [
    "PREDICATE_SYNONYMS",
    "ClaimRecord",
    "DatasetAdapter",
    "SourceRecord",
    "claim_id",
    "iso_date",
    "normalize_predicate",
    "read_jsonl",
]


@dataclass
class SourceRecord:
    """One document and who stated it, when."""
    doc_id: str
    title: str
    text: str
    url: str = ""
    dataset_id: str = ""
    source_id: str = ""          # who states it (a site, publisher, feed)
    source_name: str = ""
    source_class: str = ""       # e.g. encyclopedia, official, news, blog; adapter-defined
    reliability_prior: float | None = None
    published_at: str | None = None   # ISO date the source stated it (observed time)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ClaimRecord:
    """One statement by one source: (subject, predicate, value) with time,
    provenance and confidence. Times are ISO dates; None is unknown."""
    claim_id: str
    doc_id: str
    dataset_id: str
    subject_id: str              # an OlympicEvent event_id, or "ent:<slug>"
    subject_name: str
    predicate: str               # normalised (normalize_predicate)
    value_text: str
    value_num: float | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    observed_at: str | None = None
    source_id: str = ""
    extraction_conf: float = 1.0
    hedged: bool = False
    hedge_terms: list[str] = field(default_factory=list)
    # The document says it revises an earlier statement (a correction,
    # reallocation, update): one of the two conditions for SUPERSEDES.
    revision: bool = False


class DatasetAdapter(Protocol):
    name: str

    def documents(self, path: Path) -> Iterable[SourceRecord]: ...

    def claims(self, doc: SourceRecord) -> Iterable[ClaimRecord]: ...


# What datasets call the same attribute. Closed and general; extended per
# adapter, never from questions.
PREDICATE_SYNONYMS = {
    "winner": "gold", "champion": "gold", "gold_medalist": "gold", "gold_medallist": "gold",
    "first": "gold", "silver_medalist": "silver", "silver_medallist": "silver",
    "bronze_medalist": "bronze", "bronze_medallist": "bronze",
    "participants": "competitors", "athletes": "competitors", "entrants": "competitors",
    "competitor": "competitors", "countries": "nations", "nation": "nations", "nocs": "nations",
    "location": "venue", "place": "venue", "dates": "date", "goldnoc": "gold_noc",
}


def normalize_predicate(name: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return PREDICATE_SYNONYMS.get(key, key)


def claim_id(*parts: Any) -> str:
    """Stable id from the parts that make a claim distinct."""
    digest = hashlib.sha1("\x1f".join(str(p) for p in parts).encode("utf-8")).hexdigest()
    return f"clm-{digest[:16]}"


def iso_date(raw: Any, *, end: bool = False) -> str | None:
    """A stated date as ISO. Missing month/day become the start of the
    period, or its end with `end=True` ("2018" -> 2018-12-31)."""
    if raw is None or raw == "":
        return None
    text = str(raw).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ].*)?", text):
        return text[:10]
    nd = normalize_date(text)
    if not nd.year:
        return None
    month = nd.month or (12 if end else 1)
    if nd.day_start and nd.month:
        day = (nd.day_end or nd.day_start) if end else nd.day_start
    else:
        day = calendar.monthrange(nd.year, month)[1] if end else 1
    try:
        return date(nd.year, month, day).isoformat()
    except ValueError:
        return None


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)
