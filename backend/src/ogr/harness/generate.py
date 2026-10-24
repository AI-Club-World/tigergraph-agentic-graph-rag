"""Injection harness: evolving, conflicting and uncertain facts over the
Round-1 corpus, with questions whose ground truth is known
(ROUND2-DESIGN.md §8).

Seeds are real events and values from the parsed Round-1 infoboxes. The
generator writes *new* records (a separate dataset, `block_records`
format); it never edits a Round-1 document. Every record is marked
`synthetic` and comes from a fictional source.

Ground truth is the generator's world, fixed before any statement is
written: the true value, and which statements were made when. It is never
the resolver's choice, so the harness can show the resolver wrong.

Deterministic for a given corpus and HarnessConfig. Swap in a harder real
dataset later by replacing this module's output, not the reasoning code.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ogr.harness.templates import DATE_FORMATS, PROSE, QUESTIONS, SOURCES, Source
from ogr.ingest.infobox import ParsedDocument, event_id_for_title, parse_corpus

__all__ = ["GENERATOR_VERSION", "HarnessConfig", "HarnessOutput", "generate", "write_output"]

GENERATOR_VERSION = 1
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December")
LAST_YEAR = 2025


@dataclass(frozen=True)
class HarnessConfig:
    seed: int = 2026
    n_per_subset: int = 40
    difficulty: int = 2            # 1 easy .. 3 hard: updates, false sources, distractor closeness
    conflict_rate: float = 0.7     # conflicting subset: share of items that actually conflict
    reliable_share: float = 0.3    # share of false-value sources drawn from news (not blog/forum)
    hedge_rate: float = 0.5        # uncertain subset: share that is a lone hedged report
    hedge_error: float = 0.3       # a lone hedged report is a wrong rumour; the truth is stated nowhere
    # evolving, difficulty >= 2: a hedged rumour of a revision that never happened
    rumour_rate: float = 0.4
    noise: float = 0.5             # chance of a non-default date format
    # What records say about their source: "exact" (class and reliability),
    # "class" (class only; the class prior applies), "none" (neither: only
    # agreement between sources can tell them apart).
    reliability_info: str = "exact"
    dev_share: float = 0.5
    dataset_id: str = "r2-injected"


@dataclass
class HarnessOutput:
    records: list[dict[str, Any]] = field(default_factory=list)
    questions: list[dict[str, Any]] = field(default_factory=list)
    manifest: dict[str, Any] = field(default_factory=dict)


def _split(event_id: str, dev_share: float) -> str:
    """Per event, so no event straddles dev and test."""
    bucket = int(hashlib.sha1(event_id.encode("utf-8")).hexdigest()[:8], 16) % 1000
    return "dev" if bucket < dev_share * 1000 else "test"


def _event_part(title: str) -> str:
    match = re.search(r"Olympics\s*[–—−-]\s*(.+)$", title)
    return match.group(1) if match else title


def _person(name: str) -> bool:
    """One person's name: no list separators or footnote marks, at most five words."""
    return bool(name) and not re.search(r"[,;*()/&]|\band\b", name) and len(name.split()) <= 5


def _number_variants(value: int) -> list[str]:
    return [str(value), f"{value:,}"] if value >= 1000 else [str(value)]


class _Builder:
    def __init__(self, cfg: HarnessConfig) -> None:
        self.cfg = cfg
        self.rng = random.Random(cfg.seed)
        self.out = HarnessOutput()
        self._n = 0

    def date(self, year: int) -> tuple[str, str]:
        """(ISO, text) for a random day of `year`."""
        month = self.rng.randrange(12)
        day = self.rng.randint(1, 28)
        fmt = self.rng.choice(DATE_FORMATS) if self.rng.random() < self.cfg.noise else DATE_FORMATS[0]
        return f"{year}-{month + 1:02d}-{day:02d}", fmt(day, MONTHS[month], year)

    def source(self, cls: str) -> Source:
        return self.rng.choice(SOURCES[cls])

    def record(self, event: ParsedDocument, kind: str, fields: dict[str, str], prose: str,
               source: Source, year: int, *, effective: bool = False) -> dict[str, Any]:
        """One statement as a record. `effective`: the statement takes effect
        on its publication date (a reallocation, a ruling)."""
        self._n += 1
        doc_id = f"{self.cfg.dataset_id}-{self._n:05d}"
        iso, when = self.date(year)
        head = {"subject": event.title, **({"valid_from": iso} if effective else {})}
        block = "".join(f"  {k}: {v}\n" for k, v in {**head, **fields}.items())
        label = f" ({source.cls})" if self.cfg.reliability_info != "none" else ""
        text = (
            f"[Infobox fact record]\n{block}\n"
            f"Source: {source.name}{label}. Published: {when}.\n\n{prose}\n"
        )
        src: dict[str, Any] = {"id": source.id, "name": source.name}
        if self.cfg.reliability_info in ("exact", "class"):
            src["class"] = source.cls
        if self.cfg.reliability_info == "exact":
            src["reliability"] = source.reliability
        record = {
            "doc_id": doc_id,
            "title": f"{source.name}: {kind} – {event.title}",
            "url": f"https://example.org/{source.id.removeprefix('src:')}/{doc_id}",
            "text": text,
            "published_at": iso,
            "source": src,
            "dataset": self.cfg.dataset_id,
            "synthetic": True,
        }
        self.out.records.append(record)
        return record

    def prose(self, kind: str, **values: Any) -> str:
        return self.rng.choice(PROSE[kind]).format(**values)

    def question(self, subset: str, intent: str, event: ParsedDocument, answer: list[str],
                 gold_doc_ids: list[str], **extra: Any) -> None:
        text = self.rng.choice(QUESTIONS[intent]).format(title=event.title, year=extra.get("year", ""))
        n = sum(1 for q in self.out.questions if q["qtype"] == subset) + 1
        self.out.questions.append({
            "qid": f"r2-{subset[:3]}-{n:03d}",
            "question": text,
            "qtype": subset,
            "answer": answer,
            "gold_doc_ids": gold_doc_ids,
            "split": _split(event.event_id or event.doc_id, self.cfg.dev_share),
            "harness": {
                "intent": intent, "event_id": event.event_id, "difficulty": self.cfg.difficulty, **extra,
            },
        })

    # -- subsets ------------------------------------------------------------

    def evolving(self, event: ParsedDocument) -> bool:
        if len(event.gold) != 1 or len(event.silver) != 1 or not event.date_year:
            return False
        if not (_person(event.gold[0]) and _person(event.silver[0])):
            return False  # team events list several names in one field
        games = event.date_year
        if games + 2 > LAST_YEAR:
            return False
        old, new = event.gold[0], event.silver[0]
        part = _event_part(event.title)
        year1 = self.rng.randint(games + 2, min(games + 9, LAST_YEAR))
        realloc = self.record(
            event, "result revision", {"gold": new, "status": "correction"},
            self.prose("reallocation", event=part, old=old, new=new), self.source("official"), year1,
            effective=True,
        )
        realloc_iso = realloc["published_at"]
        history = [(None, old, event.doc_id), (realloc_iso, new, realloc["doc_id"])]
        if self.cfg.difficulty >= 3 and year1 < LAST_YEAR and self.rng.random() < 0.5:
            year2 = self.rng.randint(year1 + 1, min(year1 + 3, LAST_YEAR))
            back = self.record(
                event, "result revision", {"gold": old, "status": "correction"},
                self.prose("reinstatement", event=part, old=old, new=new), self.source("official"), year2,
                effective=True,
            )
            history.append((back["published_at"], old, back["doc_id"]))
        rumour = None
        if self.cfg.difficulty >= 2 and len(event.bronze) >= 1 and _person(event.bronze[0]) \
                and self.rng.random() < self.cfg.rumour_rate:
            rumour = event.bronze[0]
            self.record(
                event, "rumour", {"gold": rumour, "status": "unconfirmed"},
                self.prose("revision_rumour", event=part, old=history[-1][1], new=rumour),
                self.source(self.rng.choice(["blog", "forum"])),
                self.rng.randint(games + 1, min(games + 9, LAST_YEAR)),
            )

        intent = self.rng.choice(["gold_latest", "gold_original", "gold_as_of"])
        if intent == "gold_latest":
            _, value, doc = history[-1]
            self.question("evolving", intent, event, [value], [doc], scope="latest", rumour=rumour)
        elif intent == "gold_original":
            self.question("evolving", intent, event, [old], [event.doc_id], scope="original", rumour=rumour)
        else:
            last_change = int(history[-1][0][:4])
            year = self.rng.randint(games + 1, min(last_change + 1, LAST_YEAR))
            as_of = f"{year}-12-31"
            known = [h for h in history if h[0] is None or h[0] <= as_of]
            _, value, doc = known[-1]
            self.question("evolving", intent, event, [value], [doc], scope="as_of", year=year, rumour=rumour)
        return True

    def conflicting(self, event: ParsedDocument) -> bool:
        use_competitors = event.competitors and event.competitors >= 4 and self.rng.random() < 0.5
        games = event.date_year
        if not games:
            return False
        part = _event_part(event.title)
        if use_competitors:
            truth, kind, intent, gold_docs = event.competitors, "competitors", "competitors", [event.doc_id]
        else:
            truth = self.rng.randrange(200, 8000) * 10
            kind, intent, gold_docs = "attendance", "attendance", []
        conflict = self.rng.random() < self.cfg.conflict_rate
        # Truth: stated by 1-2 reliable sources (attendance has no Round-1 page to lean on).
        n_true = 1 if (use_competitors or self.cfg.difficulty >= 3) else self.rng.randint(1, 2)
        if conflict and self.cfg.difficulty <= 1:
            n_true += 1
        for _ in range(n_true):
            cls = self.rng.choice(["official", "news"])
            rec = self.record(event, f"{kind} report", {kind: f"{truth:,}"},
                              self.prose(kind, event=part, value=f"{truth:,}"), self.source(cls),
                              self.rng.randint(games, min(games + 3, LAST_YEAR)))
            gold_docs.append(rec["doc_id"])
        false_value = None
        if conflict:
            spread = (0.3, 0.6) if self.cfg.difficulty <= 1 else (0.03, 0.08)
            delta = max(1, round(truth * self.rng.uniform(*spread)))
            false_value = truth + delta if self.rng.random() < 0.5 else max(1, truth - delta)
            for _ in range(max(1, self.cfg.difficulty)):
                noisy = self.rng.choice(["blog", "forum"])
                cls = "news" if self.rng.random() < self.cfg.reliable_share else noisy
                self.record(event, f"{kind} report", {kind: f"{false_value:,}"},
                            self.prose(kind, event=part, value=f"{false_value:,}"), self.source(cls),
                            self.rng.randint(games, min(games + 3, LAST_YEAR)))
        self.question("conflicting", intent, event, _number_variants(truth), gold_docs,
                      scope="none", conflict=conflict, false_value=false_value)
        return True

    def uncertain(self, event: ParsedDocument) -> bool:
        games = event.date_year
        if not games:
            return False
        part = _event_part(event.title)
        lone = self.rng.random() < self.cfg.hedge_rate
        truth = self.rng.randrange(200, 8000) * 10
        year = min(games + 1, LAST_YEAR)
        if lone:
            # With probability hedge_error the only report is a wrong rumour:
            # the true value is stated nowhere, for any pipeline.
            wrong = self.rng.random() < self.cfg.hedge_error
            stated = round(truth * self.rng.uniform(1.15, 1.4), -1) if wrong else truth
            rec = self.record(event, "attendance estimate", {"attendance": f"about {int(stated):,}"},
                              self.prose("attendance_hedged", event=part, value=f"{int(stated):,}"),
                              self.source(self.rng.choice(["news", "blog"])), year)
            self.question("uncertain", "attendance", event, _number_variants(truth),
                          [] if wrong else [rec["doc_id"]],
                          scope="none", lone_hedged=True, answerable=not wrong, expected_confidence="low")
        else:
            estimate = round(truth * self.rng.uniform(0.9, 1.1), -2)
            self.record(event, "attendance estimate", {"attendance": f"about {int(estimate):,}"},
                        self.prose("attendance_hedged", event=part, value=f"{int(estimate):,}"),
                        self.source("news"), year)
            rec = self.record(event, "attendance report", {"attendance": f"{truth:,}"},
                              self.prose("attendance", event=part, value=f"{truth:,}"),
                              self.source("news"), year)
            self.question("uncertain", "attendance", event, _number_variants(truth), [rec["doc_id"]],
                          scope="none", lone_hedged=False, answerable=True, expected_confidence="higher")
        return True


def generate(corpus: str | Path, cfg: HarnessConfig | None = None) -> HarnessOutput:
    cfg = cfg or HarnessConfig()
    docs, _ = parse_corpus(corpus)
    events = sorted(
        (d for d in docs if d.is_olympic_event and event_id_for_title(d.title)),
        key=lambda d: d.event_id or "",
    )
    builder = _Builder(cfg)
    builder.rng.shuffle(events)
    pool = iter(events)
    counts: dict[str, int] = {}
    for subset in ("evolving", "conflicting", "uncertain"):
        made = 0
        for event in pool:
            if made >= cfg.n_per_subset:
                break
            if getattr(builder, subset)(event):
                made += 1
        counts[subset] = made
    out = builder.out
    out.manifest = {
        "generator_version": GENERATOR_VERSION,
        "config": asdict(cfg),
        "corpus": str(corpus),
        "corpus_events": len(events),
        "records": len(out.records),
        "questions": counts,
        "splits": {s: sum(1 for q in out.questions if q["split"] == s) for s in ("dev", "test")},
        "note": (
            "Synthetic statements about real events from fictional sources; ground truth is the generator's."
        ),
    }
    return out


DRY_RUN = {"evolving": 4, "conflicting": 3, "uncertain": 3}


def write_output(out: HarnessOutput, directory: str | Path, name: str | None = None) -> dict[str, Path]:
    """`<name>.jsonl` (records, a corpus), `<name>-questions.jsonl` (all),
    `-dev-` / `-test-questions.jsonl` (the splits), `-dryrun-questions.jsonl`
    (10 dev questions across the subsets: run these through the three
    pipelines before any full run), and `<name>.manifest.json`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    name = name or out.manifest.get("config", {}).get("dataset_id", "r2-injected")
    paths = {
        "corpus": directory / f"{name}.jsonl",
        "questions": directory / f"{name}-questions.jsonl",
        "manifest": directory / f"{name}.manifest.json",
        "dev": directory / f"{name}-dev-questions.jsonl",
        "test": directory / f"{name}-test-questions.jsonl",
        "dryrun": directory / f"{name}-dryrun-questions.jsonl",
    }
    def jsonl(rows: list[dict[str, Any]]) -> str:
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)

    paths["corpus"].write_text(jsonl(out.records), "utf-8")
    paths["questions"].write_text(jsonl(out.questions), "utf-8")
    for split in ("dev", "test"):
        paths[split].write_text(jsonl([q for q in out.questions if q["split"] == split]), "utf-8")
    dry = [q for subset, n in DRY_RUN.items()
           for q in [q for q in out.questions if q["split"] == "dev" and q["qtype"] == subset][:n]]
    paths["dryrun"].write_text(jsonl(dry), "utf-8")
    paths["manifest"].write_text(json.dumps(out.manifest, indent=2), "utf-8")
    return paths
