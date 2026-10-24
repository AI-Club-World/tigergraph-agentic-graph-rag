"""Generic adapter: JSONL records with a key/value block and metadata.

**[ASSUMPTION]** (ROUND2-DESIGN.md §1). The Round-2 dataset format is not
known. This adapter reads the shape the Round-1 corpus already uses, an
`[Infobox <type>]` header followed by indented `key: value` lines and then
prose, plus record-level metadata a dataset of evolving facts plausibly
carries. It is a placeholder to reconcile with the real format, and it is
also the format the injection harness writes (harness/generate.py).

Record fields read (first present wins):
  id         doc_id | id
  observed   published_at | published | timestamp | date
  source     source (string, or {id, name, class, reliability}) |
             source_id / source_name / source_class / source_reliability |
             the URL's host
Block keys:
  subject    subject | entity | about | event | page   (an event page title links to its OlympicEvent)
  validity   valid_from | effective | effective_from | as_of ;  valid_to | until | effective_to
  meta       note(s), status, source, published, supersedes, replaces, corrects (not claims)
  anything else is a claim: predicate = normalize_predicate(key), value = the text.

Claims are read from the block only. Prose is used for hedges (sentences
that mention the value) and revision cues, never parsed for values here:
prose-only datasets need the LLM extractor (gate G4).
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from ogr.datasets.base import (
    ClaimRecord,
    SourceRecord,
    claim_id,
    iso_date,
    normalize_predicate,
    read_jsonl,
)
from ogr.datasets.sources import source_of_url
from ogr.ingest.infobox import event_id_for_title, parse_infobox_fields, parse_infobox_header
from ogr.reasoning.hedges import hedge_terms, revision_terms

__all__ = ["BlockRecordAdapter"]

SUBJECT_KEYS = ("subject", "entity", "about", "event", "page")
VALID_FROM_KEYS = ("valid_from", "effective", "effective_from", "as_of")
VALID_TO_KEYS = ("valid_to", "until", "effective_to")
META_KEYS = frozenset({
    "note", "notes", "status", "source", "published", "supersedes", "replaces", "corrects",
})
REVISION_STATUS = frozenset({
    "correction", "update", "revision", "reallocation", "amended", "corrected", "revised",
})
_NUMBER = re.compile(r"^\s*(?:about|around|approximately|roughly|some|~)?\s*(\d[\d,]*(?:\.\d+)?)")


def _first(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    return next((mapping[k] for k in keys if mapping.get(k) not in (None, "")), None)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _sentences(text: str) -> list[str]:
    """Prose sentences: the header and the indented key/value lines are not prose."""
    prose = "\n".join(
        line for line in (text or "").splitlines()
        if not re.match(r"^\s*\[Infobox [^\]]+\]\s*$", line) and not re.match(r"^[ \t]+\w+\s*:", line)
    )
    return [s for s in re.split(r"(?<=[.!?])\s+", prose) if s.strip()]


class BlockRecordAdapter:
    name = "block_records"

    def __init__(self, dataset_id: str) -> None:
        self.dataset_id = dataset_id

    def documents(self, path: Path) -> Iterator[SourceRecord]:
        for record in read_jsonl(path):
            yield self.document(record)

    def document(self, record: dict[str, Any]) -> SourceRecord:
        url = record.get("url", "") or ""
        source = record.get("source")
        if isinstance(source, dict):
            sid, sname = source.get("id"), source.get("name")
            sclass, prior = source.get("class"), source.get("reliability")
        else:
            sid, sname = record.get("source_id"), source or record.get("source_name")
            sclass, prior = record.get("source_class"), record.get("source_reliability")
        if not sid and sname:
            sid = f"src:{_slug(str(sname))}"
        if not sid:
            sid, sname = source_of_url(url)
        return SourceRecord(
            doc_id=str(record.get("doc_id") or record.get("id") or ""),
            title=record.get("title", "") or "",
            text=record.get("text", "") or "",
            url=url,
            dataset_id=self.dataset_id,
            source_id=str(sid),
            source_name=str(sname or sid),
            source_class=str(sclass or ""),
            reliability_prior=float(prior) if prior is not None else None,
            published_at=iso_date(_first(record, ("published_at", "published", "timestamp", "date"))),
        )

    def claims(self, doc: SourceRecord) -> Iterator[ClaimRecord]:
        if not parse_infobox_header(doc.text):
            return
        fields = parse_infobox_fields(doc.text)
        subject_name = _first(fields, SUBJECT_KEYS) or doc.title
        subject_id = event_id_for_title(subject_name) or f"ent:{_slug(subject_name)}"
        valid_from = iso_date(_first(fields, VALID_FROM_KEYS))
        valid_to = iso_date(_first(fields, VALID_TO_KEYS), end=True)
        sentences = _sentences(doc.text)
        revision = (
            str(fields.get("status", "")).strip().lower() in REVISION_STATUS
            or any(k in fields for k in ("supersedes", "replaces", "corrects"))
            or bool(revision_terms(doc.text))
        )
        skip = set(SUBJECT_KEYS) | set(VALID_FROM_KEYS) | set(VALID_TO_KEYS) | META_KEYS
        for key, raw in fields.items():
            if key.lower() in skip:
                continue
            predicate = normalize_predicate(key)
            value = raw.strip()
            number = _NUMBER.match(value)
            mentions = [s for s in sentences if value and value.lower() in s.lower()]
            terms = hedge_terms(value)
            for sentence in mentions:
                terms += [t for t in hedge_terms(sentence) if t not in terms]
            # A number given with a qualifier ("about 30", "24 (provisional)")
            # is a partial parse, as for Round-1 infoboxes.
            exact = number is None or re.fullmatch(r"\d[\d,]*(?:\.\d+)?", value) is not None
            yield ClaimRecord(
                claim_id=claim_id(doc.dataset_id, doc.doc_id, subject_id, predicate, value),
                doc_id=doc.doc_id, dataset_id=doc.dataset_id,
                subject_id=subject_id, subject_name=subject_name,
                predicate=predicate, value_text=value,
                value_num=float(number.group(1).replace(",", "")) if number else None,
                valid_from=valid_from, valid_to=valid_to, observed_at=doc.published_at,
                source_id=doc.source_id,
                extraction_conf=1.0 if exact else 0.9,
                hedged=bool(terms), hedge_terms=terms, revision=revision,
            )
