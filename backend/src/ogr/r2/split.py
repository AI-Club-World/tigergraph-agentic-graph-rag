"""Deterministic dev/check split of the public questions (SOLUTION-DESIGN D7).

Strata come from the GOLD ANSWER SHAPE and status only (never question wording): status, answer
type (list/dict/str/int/null) and, for lists, whether items are dicts or scalars, for dicts whether
a `rows` / `found` / `claims` key is present. Inside a stratum questions are ordered by
sha256(seed:qid) and the first round(30%) (at least 1 when the stratum has 2+) go to `check`.
`check` is run only at the end; development uses `dev`.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SEED = "r2-split-v1"
CHECK_FRACTION = 0.3


def stratum(row: dict) -> str:
    answer = row.get("answer")
    if answer is None:
        kind = "null"
    elif isinstance(answer, list):
        kind = "list_dict" if answer and isinstance(answer[0], dict) else "list_scalar"
    elif isinstance(answer, dict):
        kind = "dict_" + next((k for k in ("rows", "found", "claims") if k in answer), "flat")
    else:
        kind = type(answer).__name__
    return f"{row.get('status')}|{kind}"


def _h(qid: str) -> str:
    return hashlib.sha256(f"{SEED}:{qid}".encode()).hexdigest()


def make_split(rows: list[dict]) -> dict[str, str]:
    groups: dict[str, list[str]] = {}
    for r in rows:
        groups.setdefault(stratum(r), []).append(r["qid"])
    out: dict[str, str] = {}
    for qids in groups.values():
        ordered = sorted(qids, key=_h)
        n_check = round(len(ordered) * CHECK_FRACTION)
        if len(ordered) >= 2:
            n_check = max(1, n_check)
        for i, qid in enumerate(ordered):
            out[qid] = "check" if i < n_check else "dev"
    return dict(sorted(out.items()))


def write_split(questions_path: str | Path, out_path: str | Path) -> dict[str, str]:
    text = Path(questions_path).read_text(encoding="utf-8")
    rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    split = make_split(rows)
    Path(out_path).write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")
    return split


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[4] / "docs" / "round-2" / "data"
    result = write_split(root / "questions_public.jsonl", root / "public_split.json")
    print({k: list(result.values()).count(k) for k in ("dev", "check")})
