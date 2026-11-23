"""Implementation of the `r2-score` and `r2-metrics` CLI subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ogr.r2.metrics import Prices, compute_set_metrics, update_metrics_file
from ogr.r2.output import read_answers, validate
from ogr.r2.score import ACCURACY_METHOD, score_set


def add_parsers(subparsers) -> None:
    sc = subparsers.add_parser("r2-score", help="Score public answers against gold (own fact-level scorer)")
    sc.add_argument("--questions", required=True, help="questions_public.jsonl (with gold answers)")
    sc.add_argument("--answers", required=True, help="answers JSONL")
    sc.add_argument("--out", default=None, help="Write the per-question scores here (JSON)")

    me = subparsers.add_parser("r2-metrics", help="Recompute one set of metrics.json from its answers")
    me.add_argument("--set", required=True, choices=["public", "hidden"], dest="set_name")
    me.add_argument("--answers", required=True)
    me.add_argument("--questions", default=None, help="Public only: questions with gold, for accuracy_pct")
    me.add_argument("--run-time-s", type=float, default=None,
                    help="Wall-clock seconds of the run (default: sum of per-question latency_ms)")
    me.add_argument("--out", default="out/r2/metrics.json")


def _rows(path: str) -> list[dict]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


def run_score(args: argparse.Namespace) -> int:
    result = score_set(_rows(args.questions), _rows(args.answers))
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"accuracy_pct: {result['accuracy_pct']} over {len(result['per_question'])} questions")
    return 0


def run_metrics(args: argparse.Namespace) -> int:
    records = read_answers(args.answers)
    for r in records:
        errors, warnings = validate(r)
        for msg in errors + warnings:
            print(f"{r.qid}: {msg}", file=sys.stderr)
    notes: list[str] = []
    prices = Prices.from_env()
    if prices.input_usd_per_m == 0 and prices.output_usd_per_m == 0:
        notes.append("cost_usd_total is 0: R2_LLM_INPUT_USD_PER_M / R2_LLM_OUTPUT_USD_PER_M are not set")
    run_time = args.run_time_s
    if run_time is None:
        run_time = sum(r.latency_ms for r in records) / 1000
        notes.append("total_run_time_s is the sum of latency_ms (no --run-time-s given)")
    accuracy = method = None
    if args.set_name == "public" and args.questions:
        accuracy = score_set(_rows(args.questions), [r.to_dict() for r in records])["accuracy_pct"]
        method = ACCURACY_METHOD
    metrics = compute_set_metrics(records, run_time, prices, accuracy, method)
    update_metrics_file(args.out, args.set_name, metrics, notes)
    print(f"{args.set_name}: {metrics['questions']} questions -> {args.out}")
    return 0
