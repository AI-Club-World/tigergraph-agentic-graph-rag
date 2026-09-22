"""Infobox parser and sport derivation (GRAPH-02).

Source spec: TECHNICAL-SPEC §2.1, §2.3 · Plan: implementation-plan-GRAPH.md Group 2

Corpus documents open with a bracketed infobox header followed by indented
`key: value` lines, then prose:

    [Infobox Olympic event]
      event: Men's canoe sprint K-2 1,000 metres
      games: 2012 Summer
      venue: Eton Dorney
      date: 6 to 8 August
      competitors: 24
      gold: Rudolf DombiRoland Kokeny
      prev: 2008

Decisions this module implements, each forced by something measured in the
corpus rather than assumed:

- **Sport comes from the title prefix.** No infobox carries a `sport` field.
  `<Sport> at the <Games>` parses the Olympic subset cleanly.
- **`competitors`/`nations` are typed INT** so `WHERE competitors > 37`
  becomes a native predicate instead of a parse-at-query-time hack. Some
  values are not integers (`23 teams`, `32 (16 pairs)`), so the leading
  integer is taken and `parse_confidence` drops below 1.0. The row still
  loads — a partial parse is visible to the agent rather than silently wrong.
- **`bronze` is a set.** Third-place ties appear as `bronze2`/`bronzeNOC2`.
- **Medallist names arrive concatenated** — `Rudolf DombiRoland Kokeny` is two
  people. They are split with the shared guarded splitter, so `MacLennan` is
  not torn in half. Same function the scorer uses; there is deliberately only
  one implementation.
- **Dates are normalised to typed INT fields** via the shared
  `common/dates.py`. Many dates carry no year (`6 to 8 August`), which is why
  the year is nullable rather than required.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ogr.common.dates import normalize_date
from ogr.common.names import split_multi_person

__all__ = [
    "ParsedDocument",
    "CoverageReport",
    "parse_infobox_header",
    "parse_infobox_fields",
    "derive_sport",
    "normalise_games_id",
    "parse_document",
    "parse_corpus",
]

# "[Infobox Olympic event]" on its own line, at the top of the text.
_HEADER = re.compile(r"^\s*\[Infobox ([^\]]+)\]\s*$", re.MULTILINE)
# Indented "key: value" lines belonging to the infobox block.
_FIELD = re.compile(r"^[ \t]+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
# "Canoeing at the 2012 Summer Olympics - Men's K-2 1000 metres"
_TITLE_SPORT = re.compile(r"^(.*?)\s+at\s+the\s+\d{4}\b", re.IGNORECASE)
# "2012 Summer" -> ("2012", "Summer")
_GAMES = re.compile(r"(\d{4})\s*(Summer|Winter)", re.IGNORECASE)
_LEADING_INT = re.compile(r"^\s*(\d[\d,]*)")

OLYMPIC_INFOBOX = "olympic event"


@dataclass
class ParsedDocument:
    """One corpus document after parsing. Non-Olympic docs carry only the head."""

    doc_id: str
    title: str
    url: str
    wikipedia_pageid: Any = None
    approx_tokens: int = 0
    infobox_type: str | None = None
    is_olympic_event: bool = False

    # OlympicEvent attributes (TECHNICAL-SPEC §2.1)
    event_id: str | None = None
    event_name: str | None = None
    games_id: str | None = None
    sport_name: str | None = None
    venue_name: str | None = None
    competitors: int | None = None
    competitors_text: str | None = None
    nations: int | None = None
    nations_text: str | None = None
    date_text: str | None = None
    date_year: int | None = None
    date_month: int | None = None
    date_day_start: int | None = None
    date_day_end: int | None = None
    gold: list[str] = field(default_factory=list)
    silver: list[str] = field(default_factory=list)
    bronze: list[str] = field(default_factory=list)
    gold_noc: str | None = None
    win_value: str | None = None
    win_label: str | None = None
    prev_year: int | None = None
    next_year: int | None = None
    parse_confidence: float = 1.0
    parse_notes: list[str] = field(default_factory=list)


@dataclass
class CoverageReport:
    """What parsed, what did not, and where confidence was lost."""

    total_documents: int = 0
    olympic_events: int = 0
    infobox_types: Counter = field(default_factory=Counter)
    field_present: Counter = field(default_factory=Counter)
    low_confidence: int = 0
    non_integer_competitors: list[str] = field(default_factory=list)
    missing_sport: list[str] = field(default_factory=list)
    missing_games: list[str] = field(default_factory=list)
    dates_without_year: int = 0
    concatenated_medallists: int = 0

    def as_markdown(self) -> str:
        lines = [
            "# Ingest coverage report",
            "",
            f"- Documents: **{self.total_documents}**",
            f"- Olympic-event infoboxes: **{self.olympic_events}** "
            f"({self.olympic_events / max(1, self.total_documents) * 100:.1f}%)",
            f"- Distinct infobox types: **{len(self.infobox_types)}**",
            "",
            "## Infobox types",
            "",
            "| Type | Documents |",
            "|---|---|",
        ]
        for name, count in self.infobox_types.most_common():
            lines.append(f"| {name or '(none)'} | {count} |")

        lines += [
            "",
            "## Field coverage across Olympic events",
            "",
            "| Field | Present | % |",
            "|---|---|---|",
        ]
        for name, count in self.field_present.most_common():
            pct = count / max(1, self.olympic_events) * 100
            lines.append(f"| {name} | {count} | {pct:.1f}% |")

        lines += [
            "",
            "## Parse quality",
            "",
            f"- Events with `parse_confidence < 1.0`: **{self.low_confidence}**",
            f"- Non-integer `competitors` values: **{len(self.non_integer_competitors)}**",
            f"- Events with no derivable sport: **{len(self.missing_sport)}**",
            f"- Events with no derivable games: **{len(self.missing_games)}**",
            f"- Dates carrying no year: **{self.dates_without_year}**",
            f"- Events with concatenated medallist names: **{self.concatenated_medallists}**",
        ]
        if self.non_integer_competitors:
            lines += ["", "Sample non-integer `competitors`:", ""]
            for value in self.non_integer_competitors[:10]:
                lines.append(f"- `{value}`")
        return "\n".join(lines) + "\n"


def parse_infobox_header(text: str) -> str | None:
    """The infobox type, lowercased, or None when the document has no infobox."""
    match = _HEADER.search(text)
    return match.group(1).strip().lower() if match else None


def parse_infobox_fields(text: str) -> dict[str, str]:
    """Read the indented key/value block that follows the infobox header.

    Stops at the first line that is neither indented nor blank, which is where
    the prose begins. A repeated key keeps its first value; `bronze2`-style
    numbered duplicates are separate keys and handled by the caller.
    """
    match = _HEADER.search(text)
    if not match:
        return {}

    fields: dict[str, str] = {}
    for line in text[match.end():].splitlines():
        if not line.strip():
            # A blank line inside the block is tolerated; two in a row is prose.
            if fields:
                continue
            continue
        field_match = _FIELD.match(line)
        if not field_match:
            break
        key, value = field_match.group(1), field_match.group(2).strip()
        if key not in fields and value:
            fields[key] = value
    return fields


def derive_sport(title: str) -> str | None:
    """Sport from the title prefix — no infobox carries a `sport` field."""
    match = _TITLE_SPORT.match(title or "")
    if not match:
        return None
    sport = match.group(1).strip()
    return sport or None


def normalise_games_id(raw: str | None) -> str | None:
    """`2012 Summer` -> `2012-Summer`, the form used as the Games vertex id."""
    if not raw:
        return None
    match = _GAMES.search(raw)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2).capitalize()}"


def _coerce_int(raw: str | None) -> tuple[int | None, bool]:
    """Leading integer, plus whether the value was cleanly numeric.

    Returns (value, exact). `24` -> (24, True). `23 teams` -> (23, False).
    An unparseable value is (None, False) rather than a guess.
    """
    if raw is None:
        return None, False
    stripped = raw.strip()
    if not stripped:
        return None, False
    match = _LEADING_INT.match(stripped)
    if not match:
        return None, False
    value = int(match.group(1).replace(",", ""))
    return value, match.group(0).strip() == stripped


def _medallists(fields: dict[str, str], prefix: str) -> list[str]:
    """Medallists for one place, including numbered ties, names split apart."""
    names: list[str] = []
    for key in (prefix, f"{prefix}2", f"{prefix}3"):
        raw = fields.get(key)
        if raw:
            names.extend(split_multi_person(raw))
    return names


def _year(raw: str | None) -> int | None:
    if not raw:
        return None
    match = re.search(r"\b(\d{4})\b", raw)
    return int(match.group(1)) if match else None


def parse_document(record: dict[str, Any]) -> ParsedDocument:
    """Parse one corpus record into a ParsedDocument."""
    text = record.get("text", "") or ""
    doc = ParsedDocument(
        doc_id=record.get("doc_id", ""),
        title=record.get("title", "") or "",
        url=record.get("url", "") or "",
        wikipedia_pageid=record.get("wikipedia_pageid"),
        approx_tokens=record.get("approx_tokens", 0) or 0,
        infobox_type=parse_infobox_header(text),
    )
    if doc.infobox_type != OLYMPIC_INFOBOX:
        return doc

    doc.is_olympic_event = True
    fields = parse_infobox_fields(text)
    penalties = 0.0

    doc.event_name = fields.get("event") or doc.title
    doc.games_id = normalise_games_id(fields.get("games"))
    doc.sport_name = derive_sport(doc.title)
    doc.venue_name = fields.get("venue")

    if not doc.games_id:
        doc.parse_notes.append("games not derivable")
        penalties += 0.2
    if not doc.sport_name:
        doc.parse_notes.append("sport not derivable from title")
        penalties += 0.2

    # competitors / nations: typed INT, with the raw text kept when it is not
    # cleanly numeric so the exclusion is auditable rather than invisible.
    for name in ("competitors", "nations"):
        raw = fields.get(name)
        value, exact = _coerce_int(raw)
        setattr(doc, name, value)
        if raw is not None and not exact:
            setattr(doc, f"{name}_text", raw)
            doc.parse_notes.append(f"{name} not an integer: {raw!r}")
            penalties += 0.1

    doc.date_text = fields.get("date") or fields.get("dates")
    parsed_date = normalize_date(doc.date_text)
    doc.date_year = parsed_date.year
    doc.date_month = parsed_date.month
    doc.date_day_start = parsed_date.day_start
    doc.date_day_end = parsed_date.day_end

    doc.gold = _medallists(fields, "gold")
    doc.silver = _medallists(fields, "silver")
    doc.bronze = _medallists(fields, "bronze")
    doc.gold_noc = fields.get("goldNOC")
    doc.win_value = fields.get("win_value")
    doc.win_label = fields.get("win_label")
    doc.prev_year = _year(fields.get("prev"))
    doc.next_year = _year(fields.get("next"))

    # event_id must be stable and unique: sport + games + event name.
    if doc.games_id and doc.sport_name and doc.event_name:
        slug = re.sub(r"[^a-z0-9]+", "-", doc.event_name.lower()).strip("-")
        doc.event_id = f"{doc.sport_name.lower().replace(' ', '-')}-{doc.games_id}-{slug}"
    else:
        doc.event_id = doc.doc_id

    doc.parse_confidence = round(max(0.0, 1.0 - penalties), 2)
    return doc


def parse_corpus(path: str | Path) -> tuple[list[ParsedDocument], CoverageReport]:
    """Parse every line of a corpus JSONL, returning the docs and a report.

    Nothing is dropped. A document that fails to yield an Olympic infobox is
    still returned — P1 embeds the whole corpus, including the non-Olympic
    26.7%, and filtering here would type-filter P1 by ingestion (AD-9).
    """
    docs: list[ParsedDocument] = []
    report = CoverageReport()

    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            doc = parse_document(json.loads(line))
            docs.append(doc)

            report.total_documents += 1
            report.infobox_types[doc.infobox_type] += 1
            if not doc.is_olympic_event:
                continue

            report.olympic_events += 1
            for name in (
                "event_name", "games_id", "sport_name", "venue_name",
                "competitors", "nations", "date_text", "gold", "prev_year", "next_year",
            ):
                if getattr(doc, name):
                    report.field_present[name] += 1

            if doc.parse_confidence < 1.0:
                report.low_confidence += 1
            if doc.competitors_text:
                report.non_integer_competitors.append(doc.competitors_text)
            if not doc.sport_name:
                report.missing_sport.append(doc.doc_id)
            if not doc.games_id:
                report.missing_games.append(doc.doc_id)
            if doc.date_text and doc.date_year is None:
                report.dates_without_year += 1
            if len(doc.gold) > 1:
                report.concatenated_medallists += 1

    return docs, report
