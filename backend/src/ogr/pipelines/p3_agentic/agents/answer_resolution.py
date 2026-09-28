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
- **Evidence conflicts.** When a graph row (from the page's infobox) and the
  prose of the same page state different figures for the same field
  ("nations: 23" against "24 nations took part"), the disagreement is
  reported with both values and the page. The system says the sources
  disagree instead of silently picking one; the answer is not changed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ogr.common.contracts import format_evidence_item
from ogr.common.names import normalize_answer, split_names

__all__ = ["AnswerResolution", "find_conflicts", "resolve_answer"]

# Rows from graph queries; prose chunks carry text, not entities.
_PROSE = ("similarity_search", "document_retrieval")
# A figure in page prose and the graph field it states: "24 nations",
# "a field of 311 athletes". Corpus text, not the question (NFR-7).
_PROSE_FIGURE = re.compile(
    r"\b(\d[\d,]*)\s+(nations|countries|NOCs|competitors|athletes|participants)\b", re.IGNORECASE
)
_FIELD_OF = {
    "nations": "nations", "countries": "nations", "nocs": "nations",
    "competitors": "competitors", "athletes": "competitors", "participants": "competitors",
}


@dataclass
class AnswerResolution:
    answer: str
    changed: bool
    supported: bool | None  # None: no structured evidence to check against
    note: str
    conflicts: list[str] | None = None


def find_conflicts(evidence: list[dict[str, Any]]) -> list[str]:
    """Figures the same page states differently in its infobox (graph row)
    and its prose (retrieved chunk). One line per disagreement."""
    prose_by_doc: dict[str, list[str]] = {}
    for item in evidence:
        if item.get("text") and item.get("doc_id"):
            prose_by_doc.setdefault(item["doc_id"], []).append(str(item["text"]))
    found: list[str] = []
    for row in evidence:
        doc_id = row.get("doc_id")
        if row.get("text") or not doc_id or doc_id not in prose_by_doc:
            continue
        for fld in ("nations", "competitors"):
            graph_value = row.get(fld)
            if not isinstance(graph_value, int) or graph_value <= 0:
                continue
            stated = {
                int(m.group(1).replace(",", ""))
                for text in prose_by_doc[doc_id]
                for m in _PROSE_FIGURE.finditer(text)
                if _FIELD_OF[m.group(2).lower()] == fld
            }
            other = sorted(v for v in stated if v != graph_value)
            # Only a clean disagreement: the prose states this field once,
            # differently. Several figures (per-round counts) are not a conflict.
            if len(stated) == 1 and other:
                name = row.get("title") or row.get("event_name") or doc_id
                line = f"{fld} on {name!s} ({doc_id}): infobox {graph_value}, page text {other[0]}"
                if line not in found:
                    found.append(line)
    return found


def _norm(text: str) -> str:
    return normalize_answer(text or "")


def _event_part(title: str) -> str:
    """`Athletics at the 2008 Summer Olympics – Men's marathon` -> `Men's marathon`."""
    match = re.search(r"Olympics\s*[–—−-]\s*(.+)$", title or "")
    return match.group(1) if match else ""


def resolve_answer(answer: str, evidence: list[dict[str, Any]]) -> AnswerResolution:
    rows = [e for e in evidence if e.get("source") not in _PROSE and not e.get("text")]
    conflicts = find_conflicts(evidence)
    if not answer or not rows:
        note = "no structured evidence to check the answer against"
        return AnswerResolution(answer, False, None, note, conflicts)

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
        return AnswerResolution(title, True, True, note, conflicts)

    haystack = f" {_norm(' '.join(format_evidence_item(r) for r in rows))} "
    names = [n for n in (_norm(x) for x in split_names(answer)) if n]
    supported = bool(names) and all(f" {n} " in haystack for n in names)
    if len(titles) > 1:
        note = f"answer matches {len(titles)} events among the rows; left as given"
    else:
        note = "answer found in the graph evidence" if supported else "answer not found in the graph evidence"
    return AnswerResolution(answer, False, supported, note, conflicts)
