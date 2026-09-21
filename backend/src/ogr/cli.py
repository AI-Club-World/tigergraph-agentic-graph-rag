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

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "ask":
        requested_pipelines = [p.strip().lower() for p in args.pipelines.split(",")]
        config = get_default_config()
        client = TigerGraphClient(config)

        results = {}
        for p in requested_pipelines:
            if p == "rag":
                record = run_p1_rag(query=args.query, client=client, config=config)
                results["rag"] = record.model_dump()
            else:
                print(f"Pipeline '{p}' is not yet implemented in this milestone.", file=sys.stderr)

        if args.json or len(requested_pipelines) > 1:
            print(json.dumps(results, indent=2))
        else:
            rag_record = results.get("rag")
            if rag_record:
                print(f"Pipeline: {rag_record['pipeline']}")
                print(f"Answer: {rag_record['answer']}")
                print(f"Explanation: {rag_record['explanation']}")
                print(f"Chunks returned: {rag_record['chunks_returned']}")
                print(f"Citations: {len(rag_record['citations'])}")
                print(f"Tokens: {rag_record['tokens']}")
                print(f"Latency: {rag_record['latency_ms']:.2f} ms")
                print(f"Status: {rag_record['status']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
