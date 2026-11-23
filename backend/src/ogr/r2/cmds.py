"""Implementation of the `r2-score` and `r2-metrics` CLI subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ogr.common.config import get_default_config
from ogr.r2 import run as r2_run
from ogr.r2.metrics import Prices, compute_set_metrics, update_metrics_file
from ogr.r2.output import read_answers, validate
from ogr.r2.score import ACCURACY_METHOD, score_set


def add_parsers(subparsers) -> None:
    bd = subparsers.add_parser(
        "r2-build", help="Reset the graph, install the Round-2 schema and queries, load the corpus")
    bd.add_argument("--corpus", required=True, help="corpus.jsonl")
    bd.add_argument("--counts", default="out/r2/graph_counts.json", help="Where to write vertex/edge counts")

    rn = subparsers.add_parser("r2-run", help="Answer a questions file with the Round-2 agent")
    rn.add_argument("--questions", required=True, help="questions JSONL (qid, question)")
    rn.add_argument("--out", required=True, help="answers JSONL (appended; qids already in it are skipped)")
    rn.add_argument("--backend", choices=["tigergraph", "local"], default="tigergraph",
                    help="local = LocalR2Graph over --corpus, DEV ONLY (its steps are tigergraph:false)")
    rn.add_argument("--corpus", default="docs/round-2/data/corpus.jsonl", help="Corpus for --backend local")
    rn.add_argument("--limit", type=int, default=None, help="Only the first N selected questions")
    rn.add_argument("--qids", default=None, help="Comma-separated qids to run")
    rn.add_argument("--workers", type=int, default=1, help="Parallel questions (default 1: deterministic)")
    rn.add_argument("--query-log", default=None, help="TigerGraph query log path (default R2_QUERY_LOG)")

    sc = subparsers.add_parser("r2-score", help="Score public answers against gold (own fact-level scorer)")
    sc.add_argument("--questions", required=True, help="questions_public.jsonl (with gold answers)")
    sc.add_argument("--answers", required=True, help="answers JSONL")
    sc.add_argument("--out", default=None, help="Write the per-question scores here (JSON)")
    sc.add_argument("--split", choices=["dev", "check"], default=None,
                    help="Score only this part of the public split (docs/round-2/data/public_split.json)")
    sc.add_argument("--split-file", default="docs/round-2/data/public_split.json")

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
    questions = _rows(args.questions)
    if args.split:
        split = json.loads(Path(args.split_file).read_text(encoding="utf-8"))
        questions = [q for q in questions if split.get(q["qid"]) == args.split]
    keep = {q["qid"] for q in questions}
    result = score_set(questions, [a for a in _rows(args.answers) if a.get("qid") in keep])
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    part = f" ({args.split} split)" if args.split else ""
    print(f"accuracy_pct{part}: {result['accuracy_pct']} over {len(result['per_question'])} questions")
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


def run_build(args: argparse.Namespace) -> int:
    from ogr.graph.client import TigerGraphClient
    from ogr.r2.build import build

    Path(args.counts).parent.mkdir(parents=True, exist_ok=True)
    report = build(args.corpus, TigerGraphClient(get_default_config()), counts_path=args.counts)
    print(json.dumps(report.graph, indent=2, sort_keys=True))
    print(f"graph counts -> {args.counts}")
    return 0


def run_run(args: argparse.Namespace) -> int:
    from ogr.r2.querylog import QueryLog

    config = get_default_config()
    questions = r2_run.read_questions(args.questions)
    if args.qids:
        wanted = [q.strip() for q in args.qids.split(",") if q.strip()]
        questions = [q for q in questions if q["qid"] in wanted]
    if args.limit is not None:
        questions = questions[: args.limit]
    if args.backend == "local":
        print("LOCAL BACKEND: dev only, no TigerGraph; these answers are not a submission", file=sys.stderr)
    graph = r2_run.make_graph(args.backend, args.corpus, config)
    model = r2_run.make_model(config)
    log = QueryLog(args.query_log, run_id=r2_run.new_run_id()) if args.backend == "tigergraph" else None
    s = r2_run.run_questions(questions, args.out, graph, model, config, querylog=log, workers=args.workers)
    print(f"r2-run [{args.backend}]: {s['answered_now']} answered, {s['skipped']} skipped (already in "
          f"{args.out}); statuses {s['statuses']}; tokens in/out {s['input_tokens']}/{s['output_tokens']}; "
          f"{s['seconds']}s")
    if s["failed"]:
        # Failed questions are not written; rerun the same command to retry them.
        print(f"r2-run: {len(s['failed'])} failed (rerun to retry): " + "; ".join(s["failed"]),
              file=sys.stderr)
        return 1
    return 0
