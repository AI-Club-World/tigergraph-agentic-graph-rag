"""Compare the ten Round-2 tools on TigerGraph (TigerGraphR2) and the offline model (LocalR2Graph).

    cd backend && python3 scripts/r2_parity.py [--corpus ../docs/round-2/data/corpus.jsonl] [--verbose]

Runs a few parameter sets per tool on both backends, diffs the rows (order
sensitive; floats compared to 1e-6) and prints a table. Exit 1 on any
difference. Needs the TG_* variables and a built graph.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from ogr.common.config import get_default_config
from ogr.graph.client import TigerGraphClient
from ogr.r2.corpus_model import build_model
from ogr.r2.graph_backend import TigerGraphR2
from ogr.r2.local_graph import LocalR2Graph

# (tool, kwargs). Values are generic probes (a sport, a year, a name taken from the data).
CASES: list[tuple[str, dict[str, Any]]] = [
    ("find_events", {"sport": "Swimming", "year": 2012, "season": "Summer"}),
    ("find_events", {"sport": "Athletics", "year": 2016}),
    ("find_events", {"year": 2024}),
    ("find_events", {"event_contains": "omnium"}),
    ("find_events", {"year": 2028, "sport": "Fencing"}),
    ("medals_by_nation", {"sport": "Swimming", "year": 2012, "season": "Summer"}),
    ("medals_by_nation", {"year": 2016}),
    ("medals_by_nation", {"sport": "Wrestling"}),
    ("event_series", {"event_contains": "100 metres", "sport": "Athletics"}),
    ("event_series", {"event_contains": "canoe sprint K-2 1,000"}),
    ("athlete_medals", {"name": "Rudolf Dombi"}),
    ("athlete_medals", {"name": "Roland Kökény"}),
    ("repeat_winners", {"sport": "Swimming", "medal": "gold"}),
    ("repeat_winners", {"sport": "Athletics", "medal": "gold", "season": "Summer"}),
    ("entity_facts", {"name_contains": "Dead Ringers"}),
    ("entity_facts", {"name_contains": "BHP", "entity_type": "company"}),
    ("find_entities", {"entity_type": "film", "predicate": "director", "value_contains": "Ron Howard"}),
    ("find_entities", {"entity_type": "film", "predicate": "language", "value_contains": "French"}),
    ("source_records", {"event_contains": "sabre", "year": 2028}),
    ("source_records", {"event_contains": "omnium"}),
    ("source_records", {"year": 2028}),
    ("source_records", {"event_contains": "canoe", "year": 2012}),
    ("text_search", {"terms": ["Eton Dorney", "Hungary"], "limit": 5}),
    ("text_search", {"terms": ["gold"], "limit": 3}),
    ("read_document", {"doc_id": "Q303623", "max_chars": 3000}),
    ("read_document", {"doc_id": "SYN-LA28-S001"}),
]


def norm(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    return v


def diff_rows(a: list[dict], b: list[dict]) -> str:
    if len(a) != len(b):
        return f"row count tg={len(a)} local={len(b)}"
    for i, (x, y) in enumerate(zip(a, b, strict=True)):
        x, y = norm(x), norm(y)
        if x != y:
            keys = sorted(k for k in set(x) | set(y) if x.get(k) != y.get(k))
            k = keys[0]
            return f"row {i} field {k}: tg={str(x.get(k))[:70]!r} local={str(y.get(k))[:70]!r}"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(Path(__file__).resolve().parents[2] / "docs/round-2/data/corpus.jsonl"))
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    tg = TigerGraphR2(TigerGraphClient(get_default_config()))
    local = LocalR2Graph(build_model(args.corpus))
    bad = 0
    print(f"{'tool':18} {'params':58} {'tg':>5} {'local':>5}  result")
    for tool, kw in CASES:
        a = getattr(tg, tool)(**kw)
        b = getattr(local, tool)(**kw)
        if a.error:
            res = "TG ERROR " + a.error[:120]
        elif b.error:
            res = "LOCAL ERROR " + b.error[:120]
        else:
            res = diff_rows(a.rows, b.rows) or "same"
        bad += res != "same"
        print(f"{tool:18} {str(kw)[:58]:58} {a.row_count:>5} {b.row_count:>5}  {res}")
        if args.verbose and res != "same":
            print("   tg   :", a.rows[:2])
            print("   local:", b.rows[:2])
    print(f"\n{len(CASES) - bad}/{len(CASES)} identical")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
