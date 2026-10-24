"""Round-1 corpus adapter: infobox fields as claims (ROUND2-DESIGN.md §1).

The Round-1 graph path (OlympicEvent, Q1-Q4) is not touched. These claims
are a second view of the same infoboxes, so the claim tools have the
Round-1 values to weigh new statements against: one claim per field per
page, from the encyclopedia, with the event's date as the start of its
validity and `parse_confidence` as the extraction confidence. A page gives
no publication time, so `observed_at` is None.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ogr.datasets.base import ClaimRecord, SourceRecord, claim_id, iso_date, read_jsonl
from ogr.datasets.sources import source_of_url
from ogr.ingest.infobox import ParsedDocument, parse_document
from ogr.reasoning.hedges import hedge_terms

__all__ = ["OlympicAdapter"]


class OlympicAdapter:
    name = "olympic"

    def __init__(self, dataset_id: str = "corpus") -> None:
        self.dataset_id = dataset_id
        self._parsed: dict[str, ParsedDocument] = {}

    def documents(self, path: Path) -> Iterator[SourceRecord]:
        for record in read_jsonl(path):
            doc = parse_document(record)
            self._parsed[doc.doc_id] = doc
            source_id, source_name = source_of_url(doc.url)
            yield SourceRecord(
                doc_id=doc.doc_id, title=doc.title, text=record.get("text", "") or "", url=doc.url,
                dataset_id=self.dataset_id, source_id=source_id, source_name=source_name,
                source_class="encyclopedia",
            )

    def claims(self, doc: SourceRecord) -> Iterator[ClaimRecord]:
        parsed = self._parsed.get(doc.doc_id) or parse_document(
            {"doc_id": doc.doc_id, "title": doc.title, "url": doc.url, "text": doc.text}
        )
        if not parsed.is_olympic_event:
            return
        valid_from = None
        if parsed.date_year and parsed.date_month and parsed.date_day_start:
            valid_from = iso_date(f"{parsed.date_year}-{parsed.date_month:02d}-{parsed.date_day_start:02d}")
        values: dict[str, tuple[str, float | None, str]] = {}
        for name in ("gold", "silver", "bronze"):
            names = getattr(parsed, name)
            if names:
                values[name] = ("; ".join(names), None, "; ".join(names))
        for name in ("competitors", "nations"):
            number = getattr(parsed, name)
            raw = getattr(parsed, f"{name}_text") or (str(number) if number is not None else "")
            if raw:
                values[name] = (raw, float(number) if number is not None else None, raw)
        for name, value in (("venue", parsed.venue_name), ("date", parsed.date_text),
                            ("gold_noc", parsed.gold_noc), ("win_value", parsed.win_value)):
            if value:
                values[name] = (value, None, value)
        for predicate, (text, number, raw) in values.items():
            terms = hedge_terms(raw)
            yield ClaimRecord(
                claim_id=claim_id(doc.dataset_id, doc.doc_id, parsed.event_id, predicate, text),
                doc_id=doc.doc_id, dataset_id=doc.dataset_id,
                subject_id=parsed.event_id or doc.doc_id, subject_name=doc.title,
                predicate=predicate, value_text=text, value_num=number,
                valid_from=valid_from, observed_at=None, source_id=doc.source_id,
                extraction_conf=parsed.parse_confidence, hedged=bool(terms), hedge_terms=terms,
            )
