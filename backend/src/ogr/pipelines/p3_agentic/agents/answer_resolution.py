"""Answer resolution: check the generated answer against the graph evidence it
was given, and name an event the way the graph does.

Shared by P2 and P3 (the loop stays the only difference between them); P3
also records it as a trace step. RAG has no entity layer, so it has nothing
to resolve against.

Two deterministic checks, no LLM:

- **Title resolution.** When the answer is exactly one event's short name
  ("Men's marathon") and a single evidence row carries that event, the answer
  becomes the row's page title ("Athletics at the 2008 Summer Olympics –
  Men's marathon"). Page titles are how the graph and the corpus name
  events; infobox `event_name`s are shorter, vary, and are sometimes
  unusable ("Fleet/Match" for Soling). Ambiguous matches (the same name in
  several editions among the rows) are left as they are.
- **Graph support.** Whether the answer's names occur in the structured
  evidence (whole words, after the scorer's normalization). Reported, never
  used to change the answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ogr.common.contracts import format_evidence_item
from ogr.common.names import normalize_answer, split_names

__all__ = ["AnswerResolution", "resolve_answer"]

# Rows from graph queries; prose chunks carry text, not entities.
_PROSE = ("similarity_search", "document_retrieval")


@dataclass
class AnswerResolution:
    answer: str
    changed: bool
    supported: bool | None  # None: no structured evidence to check against
    note: str


def _norm(text: str) -> str:
    return normalize_answer(text or "")


def _event_part(title: str) -> str:
    """`Athletics at the 2008 Summer Olympics – Men's marathon` -> `Men's marathon`."""
    match = re.search(r"Olympics\s*[–—−-]\s*(.+)$", title or "")
    return match.group(1) if match else ""


def resolve_answer(answer: str, evidence: list[dict[str, Any]]) -> AnswerResolution:
    rows = [e for e in evidence if e.get("source") not in _PROSE and not e.get("text")]
    if not answer or not rows:
        return AnswerResolution(answer, False, None, "no structured evidence to check the answer against")

    target = _norm(answer)
    titles = {
        row["title"]
        for row in rows
        if row.get("title")
        and target
        and target in {
            _norm(row.get("event_name") or row.get("counted_event") or ""),
            _norm(_event_part(row["title"])),
        }
    }
    if len(titles) == 1 and _norm(next(iter(titles))) != target:
        title = next(iter(titles))
        note = f"answer named the event; resolved to its page title {title!r}"
        return AnswerResolution(title, True, True, note)

    haystack = f" {_norm(' '.join(format_evidence_item(r) for r in rows))} "
    names = [n for n in (_norm(x) for x in split_names(answer)) if n]
    supported = bool(names) and all(f" {n} " in haystack for n in names)
    if len(titles) > 1:
        note = f"answer matches {len(titles)} events among the rows; left as given"
    else:
        note = "answer found in the graph evidence" if supported else "answer not found in the graph evidence"
    return AnswerResolution(answer, False, supported, note)
