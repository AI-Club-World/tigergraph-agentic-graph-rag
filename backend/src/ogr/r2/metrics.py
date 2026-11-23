"""metrics.json (brief item 3), recomputed from the answer files only.

Percentiles use the nearest-rank method: sorted values v[0..n-1], p-th percentile = v[ceil(p/100*n)-1].
Averages are rounded to 1 decimal (tokens_per_question_avg, latency_ms_avg) or 2 (per-question
step counts); cost is rounded to 4 decimals. Cost = tokens x USD-per-million prices from config
(R2_LLM_INPUT_USD_PER_M / R2_LLM_OUTPUT_USD_PER_M; default 0, which is noted in the notes file).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from ogr.r2.output import AnswerRecord


@dataclass
class Prices:
    input_usd_per_m: float = 0.0
    output_usd_per_m: float = 0.0

    @classmethod
    def from_env(cls) -> Prices:
        def num(name: str) -> float:
            try:
                return float(os.environ.get(name) or 0)
            except ValueError:
                return 0.0
        return cls(num("R2_LLM_INPUT_USD_PER_M"), num("R2_LLM_OUTPUT_USD_PER_M"))


def percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile; 0 for an empty list."""
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def compute_set_metrics(records: list[AnswerRecord], total_run_time_s: float, prices: Prices | None = None,
                        accuracy_pct: float | None = None, accuracy_method: str | None = None) -> dict:
    prices = prices or Prices()
    n = len(records)

    def avg(total: float, nd: int) -> float:
        return round(total / n, nd) if n else 0

    in_total = sum(r.input_tokens for r in records)
    out_total = sum(r.output_tokens for r in records)
    lat = [r.latency_ms for r in records]
    llm_calls = sum(1 for r in records for s in r.trace if "input_tokens" in s)
    tg_calls = sum(1 for r in records for s in r.trace if s.get("tigergraph"))
    out: dict = {"questions": n, "accuracy_pct": accuracy_pct}
    if accuracy_method is not None:
        out["accuracy_method"] = accuracy_method
    out.update({
        "not_in_corpus_answers": sum(1 for r in records if r.status == "not_in_corpus"),
        "input_tokens_total": in_total,
        "output_tokens_total": out_total,
        "tokens_per_question_avg": avg(in_total + out_total, 1),
        "latency_ms_avg": avg(sum(lat), 1),
        "latency_ms_p50": percentile(lat, 50),
        "latency_ms_p95": percentile(lat, 95),
        "llm_calls_per_question_avg": avg(llm_calls, 2),
        "tigergraph_queries_per_question_avg": avg(tg_calls, 2),
        "trace_steps_per_question_avg": avg(sum(len(r.trace) for r in records), 2),
        "answers_with_tigergraph_step": sum(1 for r in records if any(s.get("tigergraph") for s in r.trace)),
        "total_run_time_s": round(total_run_time_s, 1),
        "cost_usd_total": round(in_total * prices.input_usd_per_m / 1e6
                                + out_total * prices.output_usd_per_m / 1e6, 4),
    })
    return out


def update_metrics_file(path: str | Path, set_name: str, set_metrics: dict,
                        notes: list[str] | None = None) -> dict:
    """Merge one set ('public' | 'hidden') into metrics.json, keeping the other set; notes go to a sidecar."""
    path = Path(path)
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    data[set_name] = set_metrics
    data = {k: data[k] for k in ("public", "hidden") if k in data}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if notes:
        side = path.with_name("metrics_notes.json")
        try:
            existing = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
        except json.JSONDecodeError:
            existing = {}
        existing[set_name] = notes
        side.write_text(json.dumps(existing, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return data
