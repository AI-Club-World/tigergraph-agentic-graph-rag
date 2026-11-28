"""Shared fixtures for the Round-2 tests: a small hand-built corpus that
exercises every rule (ties, teams, boundaries, numbered keys, source records)
and, for the dev checks, the real Round-2 corpus (skipped when absent)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ogr.r2.corpus_model import CorpusModel, build_model
from ogr.r2.local_graph import LocalR2Graph

REAL_CORPUS = Path(__file__).resolve().parents[3] / "docs" / "round-2" / "data" / "corpus.jsonl"
needs_corpus = pytest.mark.skipif(not REAL_CORPUS.exists(), reason="docs/round-2/data/corpus.jsonl absent")


def event(doc_id, sport, year, season, name, *, nations=0, competitors=0, gold=(), silver=(), bronze=(),
          venue="Main Arena", synthetic=False, title_name=None, extra=""):
    """An Olympic-event record. `gold` etc. are lists of (names string, NOC)."""
    lines = ["[Infobox Olympic event]", f"  event: {name}", f"  games: {year} {season}", f"  venue: {venue}",
             "  date: 6 to 8 August"]
    if competitors:
        lines.append(f"  competitors: {competitors}")
    if nations:
        lines.append(f"  nations: {nations}")
    for kind, places in (("gold", gold), ("silver", silver), ("bronze", bronze)):
        for index, (names, noc) in enumerate(places, start=1):
            suffix = "" if index == 1 else str(index)
            lines += [f"  {kind}{suffix}: {names}", f"  {kind}NOC{suffix}: {noc}"]
    record = {
        "doc_id": doc_id,
        "title": f"{sport} at the {year} {season} Olympics – {title_name or name}",
        "url": "" if synthetic else f"https://example.org/{doc_id}",
        "text": "\n".join(lines) + f"\n\nThe {name} event. {extra}\n",
    }
    if synthetic:
        record["synthetic"] = True
        record["url"] = None
    return record


MINI = [
    event("E1", "Athletics", 2012, "Summer", "Women's 800 metres", nations=30, competitors=40,
          gold=[("Ann Alpha", "GER")], silver=[("Bea Beta", "USA")], bronze=[("Cy Gamma", "USA")]),
    event("E2", "Athletics", 2016, "Summer", "Women's 800 metres", nations=35,
          gold=[("Ann Alpha", "GER")], silver=[("Dee Delta", "USA")], bronze=[("Eve Epsilon", "KEN")]),
    event("E3", "Athletics", 2016, "Summer", "Men's 800 metres", nations=33,
          gold=[("Fay Zeta", "KEN")], silver=[("Gus Eta", "KEN")], bronze=[("Hal Theta", "USA")]),
    event("E4", "Athletics", 2016, "Summer", "Women's 800 metres hurdles", nations=20,
          gold=[("Ivy Iota", "USA")]),
    event("J1", "Judo", 2020, "Summer", "Men's 73 kg", nations=30,
          gold=[("Jon Kappa", "JPN")], silver=[("Kai Lambda", "GEO")],
          bronze=[("Lee Mu", "JPN"), ("Max Nu", "JPN")]),
    event("J2", "Judo", 2020, "Summer", "Mixed team", nations=10,
          gold=[("Dan DeltaEva Echo", "FRA")], bronze=[("Ola Xi", "JPN"), ("Pia Omicron", "BRA")]),
    event("J3", "Judo", 2024, "Summer", "Men's 73 kg", nations=31, gold=[("Jon Kappa", "JPN")]),
    event("S1", "Snowboarding", 2018, "Winter", "Men's halfpipe", nations=12, gold=[("Qin Rho", "USA")]),
    event("S2", "Snowboarding", 2022, "Winter", "Men's halfpipe", nations=14, gold=[("Qin Rho", "USA")]),
    event("L1", "Archery", 2028, "Summer", "Women's individual", nations=40,
          gold=[("Rae Sigma", "UZB")], synthetic=True, venue="Lakeside Range"),
    event("L2", "Archery", 2028, "Summer", "Men's individual", nations=41,
          gold=[("Sam Tau", "UZB")], synthetic=True, venue="Lakeside Range"),
    {"doc_id": "F1", "title": "Splash (film)", "url": "https://example.org/F1",
     "text": "[Infobox film]\n  name: Splash\n  director: Ron Howard\n  released: 1984-03-09\n"
             "  budget: $8 million\n  gross: $69.8 million\n\nSplash is a film.\n"},
    {"doc_id": "F2", "title": "Cocoon (film)", "url": "https://example.org/F2",
     "text": "[Infobox film]\n  name: Cocoon\n  director: Someone Else\n  budget: $17.5 million\n\nCocoon.\n"},
    {"doc_id": "P1", "title": "Jane Governor", "url": "https://example.org/P1",
     "text": "[Infobox officeholder]\n  name: Jane Governor\n  jr/sr: United States Senator\n"
             "  office1: Governor of Maine\n  predecessor1: Old Gov\n  successor1: New Gov\n"
             "  term_start1: January 5, 1995\n\nJane was governor in Maine.\n"},
    {"doc_id": "Z1", "title": "Plain page", "url": "https://example.org/Z1", "text": "No infobox here.\n"},
    {"doc_id": "SYN-A", "title": "Archery women's individual - scoreboard", "url": None, "synthetic": True,
     "text": "[Synthetic document: this record describes fictional LA 2028 events.]\n\n"
             "Source: Venue scoreboard operator\nPublished: 2028-07-23 21:09 PDT (UTC−07:00)\n\n"
             "Women's individual archery: Rae Sigma leads at Lakeside Range."},
    {"doc_id": "SYN-B", "title": "Federation notice", "url": None, "synthetic": True,
     "text": "[Synthetic document: this record describes fictional LA 2028 events.]\n\n"
             "Source: International archery federation (signed notice)\nPublished: 2029-01-20 10:00 CET (UTC+01:00)\n\n"
             "Sam Tau is confirmed as gold medallist."},
]


@pytest.fixture(scope="session")
def mini_corpus(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("r2") / "mini.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in MINI) + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="session")
def mini_model(mini_corpus) -> CorpusModel:
    return build_model(mini_corpus)


@pytest.fixture(scope="session")
def mini(mini_model) -> LocalR2Graph:
    return LocalR2Graph(mini_model)


@pytest.fixture(scope="session")
def real_model() -> CorpusModel:
    if not REAL_CORPUS.exists():
        pytest.skip("real corpus absent")
    return build_model(REAL_CORPUS)


@pytest.fixture(scope="session")
def real(real_model) -> LocalR2Graph:
    return LocalR2Graph(real_model)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_settle_wait(monkeypatch):
    """The build waits for server-side counts to settle; stand-in clients need no wait."""
    monkeypatch.setattr("ogr.r2.build.SETTLE_INTERVAL_S", 0.0)
