"""Command line interface for OGR pipelines."""

from __future__ import annotations

import argparse
import json
import sys

from ogr.common.config import get_default_config
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p1_rag import run_p1_rag


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ogr.cli", description="OGR CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="Ask a question through one or more pipelines")
    ask_parser.add_argument("query", type=str, help="The question text to evaluate")
    ask_parser.add_argument(
        "--pipelines",
        type=str,
        default="rag",
        help="Comma-separated list of pipelines to run (e.g. 'rag', 'graphrag', 'agentic_graphrag')",
    )
    ask_parser.add_argument("--json", action="store_true", help="Output full JSON record")
    ask_parser.add_argument(
        "--show-trace",
        action="store_true",
        help="Print the agentic investigation trace step by step",
    )

    subparsers.add_parser("verify", help="Check the LLM and TigerGraph endpoints are reachable")

    coverage_parser = subparsers.add_parser(
        "coverage", help="Parse the corpus and write the GRAPH-02 ingest coverage report"
    )
    coverage_parser.add_argument("--corpus", type=str, default="data/corpus.jsonl")
    coverage_parser.add_argument("--out", type=str, default="out/ingest-coverage.md")

    batch_parser = subparsers.add_parser(
        "batch", help="Run a JSONL question set through all three pipelines (EVAL-04)"
    )
    batch_parser.add_argument("questions", type=str, help="Path to a Question JSONL file")
    batch_parser.add_argument("--out", type=str, required=True, help="Output BatchRecord JSONL path")
    batch_parser.add_argument("--run-id", type=str, default=None, help="Defaults to a UTC timestamp")

    return parser


def _print_trace(record) -> None:
    """Print the agentic TraceStep[] — one line per step (TECHNICAL-SPEC §6.3)."""
    steps = record.trace or []
    if not steps:
        print("  (no trace recorded)")
        return
    for step in steps:
        marker = "  <- STRATEGY CHANGE" if step.strategy_change else ""
        print(
            f"  [{step.step_n}] {step.agent_type} via {step.tool_called} | "
            f"tokens={step.tokens.total} chunks={step.chunks_returned} "
            f"citations={step.citations_count} {step.latency_ms:.0f}ms{marker}"
        )
        if step.notes:
            print(f"      {step.notes}")
    print(f"  stop_reason: {record.stop_reason}")


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "verify":
        from ogr.verify import run as run_verify

        return run_verify()

    if args.command == "coverage":
        from pathlib import Path

        from ogr.ingest.infobox import parse_corpus

        _, report = parse_corpus(args.corpus)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.as_markdown(), encoding="utf-8")
        print(f"Wrote {out_path} ({report.olympic_events}/{report.total_documents} Olympic events)")
        return 0

    if args.command == "batch":
        from datetime import UTC, datetime

        from ogr.eval.batch_runner import run_batch_sync, run_config_header
        from ogr.pipelines.p2_graphrag import run_p2_graphrag
        from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic

        config = get_default_config()
        client = TigerGraphClient(config)
        run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

        pipelines = {
            "rag": lambda q: run_p1_rag(query=q, client=client, config=config),
            "graphrag": lambda q: run_p2_graphrag(query=q, client=client, config=config),
            "agentic_graphrag": lambda q: run_p3_agentic(query=q, tg_client=client, config=config),
        }
        count = run_batch_sync(
            questions_path=args.questions,
            out_path=args.out,
            pipelines=pipelines,
            run_id=run_id,
            run_config=run_config_header(config),
            pool_size=config.pool_size,
        )
        print(f"Batch {run_id}: ran {count} question(s), wrote to {args.out}")
        return 0

    if args.command == "ask":
        requested_pipelines = [p.strip().lower() for p in args.pipelines.split(",")]
        config = get_default_config()
        client = TigerGraphClient(config)

        records = {}
        for p in requested_pipelines:
            if p == "rag":
                records["rag"] = run_p1_rag(query=args.query, client=client, config=config)
            elif p in ("graphrag", "graph"):
                from ogr.pipelines.p2_graphrag import run_p2_graphrag

                records["graphrag"] = run_p2_graphrag(
                    query=args.query, client=client, config=config
                )
            elif p in ("agentic", "agentic_graphrag"):
                from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic

                records["agentic_graphrag"] = run_p3_agentic(
                    query=args.query, tg_client=client, config=config
                )
            else:
                print(f"Pipeline '{p}' is not yet implemented in this milestone.", file=sys.stderr)

        if args.json:
            print(json.dumps({k: v.model_dump() for k, v in records.items()}, indent=2))
            return 0

        for name, record in records.items():
            print(f"Pipeline: {record.pipeline}")
            print(f"Answer: {record.answer}")
            print(f"Explanation: {record.explanation}")
            print(f"Chunks returned: {record.chunks_returned}")
            print(f"Citations: {len(record.citations)}")
            print(f"Tokens: {record.tokens.model_dump()} ({record.token_source})")
            print(f"Latency: {record.latency_ms:.2f} ms")
            print(f"Status: {record.status}")
            if args.show_trace and name == "agentic_graphrag":
                print("Trace:")
                _print_trace(record)
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
