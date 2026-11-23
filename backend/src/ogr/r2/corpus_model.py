"""In-memory model of the Round-2 corpus: what the TigerGraph build loads and
what `LocalR2Graph` answers from (SOLUTION-DESIGN §2).

One pass over the corpus builds, with no LLM and no network:

- events and their medallists (from the Olympic infobox, with NOCs, via the
  parser's `medallist_slots`), athletes and WON edges;
- an Entity per non-Olympic infobox document and one Fact per infobox key;
- the 39 LA 2028 source records with source name, publication time (original
  string and ISO 8601 with offset), authority class and body text;
- REPORTS_ON links from a record to the LA 2028 events it is about;
- the text chunks every text tool reads (the Round-1 chunker, no embeddings).

Everything is deterministic and contains no question-specific logic: the
authority classes come from a general lexicon over the `Source:` line, and the
links from a general rule over event names, sport words and venues.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ogr.common.names import normalize_answer
from ogr.ingest.chunk_embed import Chunk, chunk_document
from ogr.ingest.infobox import (
    ParsedDocument,
    medallist_slots,
    parse_document,
    parse_infobox_facts,
    parse_infobox_fields,
)

__all__ = [
    "AUTHORITY_LEXICON", "SOURCE_MARKER", "CorpusModel", "Event", "Medallist", "Athlete", "WonEdge",
    "Entity", "Fact", "SourceRecord", "ReportsOn", "build_model", "classify_authority",
    "parse_number", "parse_published", "athlete_id", "contains_norm",
]

SOURCE_MARKER = "[Synthetic document: this record"
LA_GAMES = "2028-Summer"
MEDALS = ("gold", "silver", "bronze")

# Ordered: the first matching class wins. "Signed" or "jury" outranks the kind
# of desk that issued it (a signed clock log from a control desk is official);
# an unreliable marker outranks a media word (a fan blog is not a news item);
# the media words come last because "bulletin" alone is only secondary.
AUTHORITY_LEXICON: list[tuple[str, re.Pattern[str]]] = [
    ("official", re.compile(
        r"signed|\bjury\b|certified|certificate|binding|race director|transfer notice"
        r"|\bregister\b|\bbinding\b", re.I)),
    ("unreliable", re.compile(
        r"\bblog\b|\bfan\b|spectator|voice note|volunteer|tourism|ticket|aggregator|legacy|coaching"
        r"|third-party", re.I)),
    ("operational", re.compile(
        r"scoreboard|timing data|timing contractor|registration|schedule|access log|control desk"
        r"|operations|inspector|planning office|security desk", re.I)),
    ("secondary", re.compile(
        r"\bnews|newsletter|bulletin|headline|media feed|media desk|\bfeed\b", re.I)),
]


def classify_authority(source_name: str) -> str:
    """Authority class of a `Source:` line, or "unclassified" when no rule fires."""
    for label, pattern in AUTHORITY_LEXICON:
        if pattern.search(source_name or ""):
            return label
    return "unclassified"


def athlete_id(name: str) -> str:
    return normalize_answer(name)


def contains_norm(haystack: str, needle: str) -> bool:
    """`needle` occurs in `haystack`, both already normalized, starting at a
    word boundary: "mens 100 metres" must not match inside "womens 100 metres"."""
    if not needle:
        return True
    return f" {needle}" in f" {haystack}"


@dataclass
class Medallist:
    athlete_id: str
    name: str
    noc: str
    medal: str
    place: int  # 1..3: which medal of this kind (ties and team places)


@dataclass
class Event:
    event_id: str
    doc_id: str
    title: str
    event_name: str
    sport: str
    games_id: str
    year: int
    season: str
    date_text: str
    venue: str
    competitors: int
    nations: int
    synthetic: bool
    medallists: list[Medallist] = field(default_factory=list)

    @property
    def event_norm(self) -> str:
        return normalize_answer(self.event_name)

    @property
    def title_norm(self) -> str:
        return normalize_answer(self.title)

    @property
    def event_key(self) -> str:
        """Identity of the event across Games: the normalized event part of the
        page title ("men's +100 kg"). Infobox event names drift between years
        ("Men's +100kg", "Women's judo 78 kg category") where titles do not, so
        grouping editions by title finds the repeat winners the infobox names miss."""
        match = _TITLE_EVENT.search(self.title)
        return normalize_answer(match.group(1)) if match else self.event_norm

    def by_medal(self, medal: str) -> list[Medallist]:
        return [m for m in self.medallists if m.medal == medal]


@dataclass
class Athlete:
    athlete_id: str
    name: str


@dataclass
class WonEdge:
    athlete_id: str
    event_id: str
    medal: str
    noc: str
    place: int
    event_key: str = ""


@dataclass
class Fact:
    entity_id: str
    doc_id: str
    predicate: str
    value_text: str
    value_num: float | None = None
    note: str = ""  # currency or unit of value_num ("USD", "minutes", "year")

    @property
    def claim_id(self) -> str:
        return f"{self.entity_id}:{self.predicate}"


@dataclass
class Entity:
    entity_id: str
    doc_id: str
    name: str
    entity_type: str


@dataclass
class SourceRecord:
    doc_id: str
    title: str
    source_name: str
    published_text: str
    published_at: str
    authority: str
    text: str


@dataclass
class ReportsOn:
    record_id: str
    event_id: str
    score: float


@dataclass
class CorpusModel:
    events: list[Event] = field(default_factory=list)
    athletes: dict[str, Athlete] = field(default_factory=dict)
    won: list[WonEdge] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    sources: list[SourceRecord] = field(default_factory=list)
    links: list[ReportsOn] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    documents: list[ParsedDocument] = field(default_factory=list)
    titles: dict[str, str] = field(default_factory=dict)

    def event_by_id(self) -> dict[str, Event]:
        return {e.event_id: e for e in self.events}


# --- numbers ---------------------------------------------------------------

_SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12, "crore": 1e7, "lakh": 1e5}
_CURRENCIES = {
    "$": "USD", "US$": "USD", "USD": "USD", "£": "GBP", "GBP": "GBP", "€": "EUR", "EUR": "EUR",
    "¥": "JPY", "₹": "INR", "HK$": "HKD", "C$": "CAD", "A$": "AUD", "CA$": "CAD", "NZ$": "NZD",
}
_PLAIN = re.compile(r"^\d[\d,]*(\.\d+)?$")
_UNIT = re.compile(r"^(\d[\d,]*(?:\.\d+)?)\s*(minutes?|mins?)$", re.I)
_MONEY = re.compile(
    r"^(?P<cur>US\$|HK\$|CA\$|NZ\$|C\$|A\$|USD|GBP|EUR|[$£€¥₹])?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*(?P<scale>thousand|million|billion|trillion|crores?|lakhs?)?"
    r"(?P<rest>.*)$", re.I)


def _to_float(text: str) -> float:
    return float(text.replace(",", ""))


def parse_number(value: str) -> tuple[float | None, str]:
    """(number, note) for a clean numeric infobox value, else (None, "").

    Clean means one number: `24`, `1988`, `142 minutes`, `$32 million` (32e6,
    note USD), `£10 million`, `$1.2 billion`, `15 crore`. A range
    (`$60-70 million`), a list or prose is not clean and stays text only, so a
    numeric comparison never rests on a guessed figure. The currency is kept
    in the note because the number alone drops it.
    """
    text = (value or "").strip()
    if not text:
        return None, ""
    if _PLAIN.match(text):
        number = _to_float(text)
        is_year = re.fullmatch(r"\d{4}", text) is not None and 1000 <= number <= 2199
        return number, "year" if is_year else ""
    unit = _UNIT.match(text)
    if unit:
        return _to_float(unit.group(1)), "minutes"
    money = _MONEY.match(text)
    if not money:
        return None, ""
    scale, cur, rest = money.group("scale"), money.group("cur"), money.group("rest").strip()
    if not scale and not cur:
        return None, ""
    if rest and rest[0] not in "([<":  # "-70 million" after a range, prose, a second figure
        return None, ""
    key = scale.lower().rstrip("s") if scale else ""
    factor = _SCALES.get(key, 1.0)
    note = _CURRENCIES.get(cur or "", "") or (key if key in ("crore", "lakh") else "")
    return _to_float(money.group("num")) * factor, note


# --- source records --------------------------------------------------------

_SOURCE_LINE = re.compile(r"^Source:\s*(.+)$", re.M)
_PUBLISHED_LINE = re.compile(r"^Published:\s*(.+)$", re.M)
_STAMP = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?\s*\S*\s*"
    r"\(UTC\s*([−+\-–])\s*(\d{1,2}):?(\d{2})\)")


def parse_published(text: str) -> str:
    """`2028-07-23 22:15 PDT (UTC−07:00)` -> `2028-07-23T22:15:00-07:00`; "" when
    the stamp has no parseable offset. The UTC offset is the stated one; the
    zone abbreviation is not interpreted."""
    match = _STAMP.search(text or "")
    if not match:
        return ""
    year, month, day, hour, minute, second, sign, off_h, off_m = match.groups()
    delta = timedelta(hours=int(off_h), minutes=int(off_m))
    if sign != "+":
        delta = -delta
    stamp = datetime(int(year), int(month), int(day), int(hour), int(minute), int(second or 0),
                     tzinfo=timezone(delta))
    return stamp.isoformat()


def parse_source_record(record: dict[str, Any]) -> SourceRecord:
    text = record.get("text", "") or ""
    source = _SOURCE_LINE.search(text)
    published = _PUBLISHED_LINE.search(text)
    body = text[published.end():] if published else (text[source.end():] if source else text)
    source_name = source.group(1).strip() if source else ""
    return SourceRecord(
        doc_id=record["doc_id"], title=record.get("title", "") or "", source_name=source_name,
        published_text=published.group(1).strip() if published else "",
        published_at=parse_published(published.group(1)) if published else "",
        authority=classify_authority(source_name), text=body.strip(),
    )


# --- REPORTS_ON ------------------------------------------------------------

_TITLE_EVENT = re.compile(r"Olympics\s*[–—−-]\s*(.+)$", re.I)


def _event_names(event: Event) -> set[str]:
    """Normalized names an article may use for the event: the infobox `event`
    and the event part of the page title. Infobox names are sometimes untidy
    ("Table tennis - men's singles"), titles are not; a one-word name
    ("men's", the triathlon title) says too little to match on."""
    names = {event.event_norm}
    match = _TITLE_EVENT.search(event.title)
    if match:
        names.add(normalize_answer(match.group(1)))
    return {n for n in names if n and (len(n.split()) >= 2 or n == event.event_norm)}


def link_records(sources: list[SourceRecord], events: list[Event]) -> list[ReportsOn]:
    """Link each source record to the LA 2028 events it is about.

    Strong link (score 1.0): an event's normalized name appears in the record's
    title or text (word-aligned, so "men's individual" is not found in
    "women's individual") and the event's sport name is there too, or the name
    is a distinctive one (three or more words, one LA 2028 event, e.g. "men's
    100 metres"). A name shared by several sports ("men's singles") therefore
    needs the sport word.

    Venue link (0.5): the name is there and so is the event's venue, but not
    the sport, which leaves every event of that name at the venue possible.

    Name-only link (0.25): the name is there with neither sport nor venue, so
    every event of that name stays possible ("men's singles" in two sports).
    Kept only when the record has no stronger link: next to one, a name found
    inside another event's name ("individual" in golf and archery) is noise.

    Athlete link (0.5), only for a record with no stronger link: the full name
    of an LA 2028 medallist (two or more words), or a surname together with
    that event's sport word, appears ("Two Tursunovs on the archery podiums").
    """
    la_events = [e for e in events if e.games_id == LA_GAMES]
    names = {e.event_id: _event_names(e) for e in la_events}
    name_count: dict[str, int] = {}
    for e in la_events:
        for n in names[e.event_id]:
            name_count[n] = name_count.get(n, 0) + 1
    medallist_events: dict[str, set[str]] = {}
    surname_events: dict[str, set[str]] = {}
    for e in la_events:
        for m in e.medallists:
            parts = m.athlete_id.split()
            if len(parts) >= 2:
                medallist_events.setdefault(m.athlete_id, set()).add(e.event_id)
            if parts and len(parts[-1]) >= 4:
                surname_events.setdefault(parts[-1], set()).add(e.event_id)
    by_id = {e.event_id: e for e in la_events}

    links: list[ReportsOn] = []
    for record in sources:
        padded = f" {normalize_answer(f'{record.title} {record.source_name} {record.text}')} "
        scores: dict[str, float] = {}
        for e in la_events:
            matched = [n for n in names[e.event_id] if f" {n} " in padded]
            if not matched:
                continue
            if f" {normalize_answer(e.sport)} " in padded or any(
                name_count[n] == 1 and len(n.split()) >= 3 for n in matched
            ):
                scores[e.event_id] = 1.0
            elif e.venue and f" {normalize_answer(e.venue)} " in padded:
                scores[e.event_id] = 0.5
            else:
                scores[e.event_id] = 0.25
        if scores and max(scores.values()) > 0.25:
            scores = {i: v for i, v in scores.items() if v > 0.25}
        if not scores:
            for athlete, event_ids in medallist_events.items():
                if f" {athlete} " in padded:
                    scores.update({i: 0.5 for i in event_ids})
            for surname, event_ids in surname_events.items():
                if f" {surname} " in padded:
                    scores.update({
                        i: 0.5 for i in event_ids if f" {normalize_answer(by_id[i].sport)} " in padded
                    })
        links.extend(ReportsOn(record.doc_id, i, score) for i, score in sorted(scores.items()))
    return links


# --- build -----------------------------------------------------------------

def _event_from(doc: ParsedDocument, record: dict[str, Any]) -> Event:
    games = doc.games_id or ""
    year, _, season = games.partition("-")
    event = Event(
        event_id=doc.event_id or doc.doc_id, doc_id=doc.doc_id, title=doc.title,
        event_name=doc.event_name or "", sport=doc.sport_name or "", games_id=games,
        year=int(year) if year.isdigit() else 0, season=season, date_text=doc.date_text or "",
        venue=doc.venue_name or "", competitors=doc.competitors or 0, nations=doc.nations or 0,
        synthetic=bool(record.get("synthetic")),
    )
    fields = parse_infobox_fields(record.get("text", "") or "")
    for medal in MEDALS:
        for place, name, noc in medallist_slots(fields, medal):
            if not athlete_id(name):
                continue
            event.medallists.append(Medallist(athlete_id(name), name, noc, medal, place))
    return event


def build_model(corpus_path: str | Path) -> CorpusModel:
    """Parse the corpus JSONL into a `CorpusModel`. Nothing is dropped."""
    model = CorpusModel()
    records: list[dict[str, Any]] = []
    with open(corpus_path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    for record in records:
        text = record.get("text", "") or ""
        doc = parse_document(record)
        model.documents.append(doc)
        model.titles[doc.doc_id] = doc.title
        model.chunks.extend(chunk_document(doc.doc_id, text))

        if text.startswith(SOURCE_MARKER):
            model.sources.append(parse_source_record(record))
        elif doc.is_olympic_event:
            event = _event_from(doc, record)
            model.events.append(event)
            for m in event.medallists:
                model.athletes.setdefault(m.athlete_id, Athlete(m.athlete_id, m.name))
                model.won.append(
                    WonEdge(m.athlete_id, event.event_id, m.medal, m.noc, m.place, event.event_key))
        elif doc.infobox_type:
            entity = Entity(f"ent:{doc.doc_id}", doc.doc_id, doc.title, doc.infobox_type)
            model.entities.append(entity)
            for predicate, value in parse_infobox_facts(text).items():
                number, note = parse_number(value)
                model.facts.append(Fact(entity.entity_id, doc.doc_id, predicate, value, number, note))

    model.links = link_records(model.sources, model.events)
    return model
