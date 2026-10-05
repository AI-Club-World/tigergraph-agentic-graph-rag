"""Command line interface for OGR pipelines."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ogr.common.config import get_default_config
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p1_rag import run_p1_rag


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m ogr.cli", description="OGR CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="Ask a question through one or more pipelines")
    ask_parser.add_argument(
        "--embedding-model", default=None,
        help="Search with this model (default: the one Settings made active); it must be complete",
    )
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

    report_parser = subparsers.add_parser(
        "report", help="Markdown report for a run: where the agent pays for itself, routing, agents"
    )
    report_parser.add_argument("run", type=str, help="Run JSONL file (out/<run_id>.jsonl)")
    report_parser.add_argument("--out", type=str, default=None, help="Write here instead of stdout")

    export_parser = subparsers.add_parser(
        "export", help="Submission JSON for a run: answers, tokens, citations and agentic traces"
    )
    export_parser.add_argument("run", type=str, help="Run JSONL file (out/<run_id>.jsonl)")
    export_parser.add_argument("--out", type=str, required=True)

    verify_parser = subparsers.add_parser(
        "verify", help="Check the LLM, embedding and TigerGraph endpoints are reachable"
    )
    verify_parser.add_argument(
        "--pre-build",
        action="store_true",
        help="Before the first build: report missing GSQL queries without failing (build installs them)",
    )

    coverage_parser = subparsers.add_parser(
        "coverage", help="Parse the corpus and write the GRAPH-02 ingest coverage report"
    )
    coverage_parser.add_argument("--corpus", type=str, default="data/corpus/corpus.jsonl")
    coverage_parser.add_argument("--out", type=str, default="out/ingest-coverage.md")

    batch_parser = subparsers.add_parser(
        "batch", help="Run a JSONL question set through all three pipelines (EVAL-04)"
    )
    batch_parser.add_argument(
        "--embedding-model", default=None,
        help="Search with this model (default: the one Settings made active); it must be complete",
    )
    batch_parser.add_argument("questions", type=str, help="Path to a Question JSONL file")
    batch_parser.add_argument("--out", type=str, required=True, help="Output BatchRecord JSONL path")
    batch_parser.add_argument("--run-id", type=str, default=None, help="Defaults to a UTC timestamp")
    batch_parser.add_argument(
        "--mode",
        choices=["throughput", "timing"],
        default=None,
        help="throughput: pool of RUN_POOL_SIZE (accuracy/tokens); timing: pool 1 (latency figures). "
        "Defaults to RUN_LATENCY_MODE",
    )

    build_parser_ = subparsers.add_parser(
        "build", help="Chunk+embed the corpus, install schema, load the graph, install Q1-Q5"
    )
    build_parser_.add_argument("--corpus", type=str, default="data/corpus/corpus.jsonl")
    build_parser_.add_argument(
        "--vector-timeout", type=float, default=600.0, help="Seconds to wait for Ready_for_query"
    )

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


def _build(corpus: str, vector_timeout_s: float) -> int:
    """The same stages as the API's POST /build, headless, for `make reproduce`.
    Ends with the vector readiness gate (TECHNICAL-SPEC §11): a benchmark must
    not start before the index reports Ready_for_query."""
    from ogr.common.embedding_models import resolve_model
    from ogr.common.embeddings import embedding_backend
    from ogr.graph.schema import install_queries, install_schema
    from ogr.graph.vector_status import VectorNotReadyError, wait_until_ready
    from ogr.ingest.chunk_embed import chunk_and_embed_corpus, embed_chunks
    from ogr.ingest.embedding_index import EmbeddingStore
    from ogr.ingest.infobox import parse_corpus
    from ogr.ingest.load import load_graph
    from ogr.ingest.registry import DatasetRegistry

    config = get_default_config()
    client = TigerGraphClient(config)
    client._ensure_connection()
    if client.conn is None:
        print("TigerGraph unreachable — set TG_HOST and credentials (run `verify`).", file=sys.stderr)
        return 1
    out_dir = OUT_DIR
    store = EmbeddingStore(out_dir / "embeddings.json")
    # The model Settings last made active, else EMBEDDING_MODEL.
    model = resolve_model(store.active() or config.embedding_model)
    print(f"chunk+embed {corpus} with {model.label} ({model.dim}-dim) ...")
    chunks = chunk_and_embed_corpus(corpus, config.chunk_tokens, config.chunk_overlap, embed=False)
    embed_chunks(chunks, model.key, strict=True)  # never hash noise into an index
    print(f"  {len(chunks)} chunks; installing schema (resets the graph and every loaded dataset) ...")
    install_schema(client)
    # Same registry the API's multi-dataset build keeps; the reset above
    # leaves exactly this one dataset in the graph.
    registry = DatasetRegistry(out_dir / "datasets.json")
    registry.reset(model.key, model.dim)
    store.reset(model.key)
    docs, _report = parse_corpus(corpus)
    print(f"  loading {len(docs)} documents ...")
    load = load_graph(client, docs, chunks, embedding_model=model.key)
    registry.record(
        Path(corpus).stem,
        ids={
            "doc_ids": [d.doc_id for d in docs],
            "event_ids": [d.event_id or d.doc_id for d in docs if d.is_olympic_event],
            "chunk_ids": [c.chunk_id for c in chunks],
        },
        counts={
            "documents": load.documents, "events": load.olympic_events, "chunks": load.chunks,
            "vectors": load.chunks, "embedding_model": model.key,
            "embedding_backend": embedding_backend(model.key),
        },
        file_bytes=Path(corpus).stat().st_size,
    )
    print("  installing Q1-Q5 ...")
    try:
        install_queries(client)
        wait_until_ready(config, timeout_s=vector_timeout_s, conn=client.conn)
    except (RuntimeError, VectorNotReadyError) as e:
        print(str(e), file=sys.stderr)
        return 1
    store.add_covered(model.key, [c.chunk_id for c in chunks], embedding_backend(model.key))
    if not store.active():
        store.set_active(model.key)
    print("Build complete; vector index Ready_for_query.")
    return 0


OUT_DIR = Path(__file__).resolve().parents[3] / "out"


def _query_config(requested: str | None = None):
    """The config a CLI query or batch runs with, or None (after printing why).

    Same rule as the API: the embedding model is the one Settings made
    active (or `--embedding-model`), and it must have complete embeddings
    for the corpus — a query is never searched against an incomplete or
    another model's index."""
    from ogr.common.embedding_models import EMBEDDING_MODELS, UnknownEmbeddingModel, resolve_model
    from ogr.ingest.embedding_index import EmbeddingStore
    from ogr.ingest.registry import DatasetRegistry

    config = get_default_config()
    store = EmbeddingStore(OUT_DIR / "embeddings.json")
    try:
        model = resolve_model(requested or store.active() or config.embedding_model)
    except UnknownEmbeddingModel as e:
        print(str(e), file=sys.stderr)
        return None
    corpus = DatasetRegistry(OUT_DIR / "datasets.json").all_chunk_ids()
    status = store.model_status(model.key, corpus)
    if not status["complete"]:
        complete = [EMBEDDING_MODELS[k].key for k in store.complete_models(corpus)]
        print(
            f"{model.label} has no complete embeddings for this corpus (state: {status['state']}, "
            f"{status['chunks_done']}/{status['chunks_total']} chunks). "
            + (f"Complete models: {', '.join(complete)} — pass --embedding-model." if complete
               else "Build the dataset first (`ogr.cli build`)."),
            file=sys.stderr,
        )
        return None
    return config.model_copy(update={"embedding_model": model.key, "embedding_dim": model.dim})


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "report":
        from ogr.eval.report import build_report

        text = build_report(Path(args.run))
        if args.out:
            Path(args.out).write_text(text + "\n", encoding="utf-8")
            print(f"Report written to {args.out}")
        else:
            print(text)
        return 0

    if args.command == "export":
        from ogr.eval.report import write_export

        count = write_export(Path(args.run), Path(args.out))
        print(f"Exported {count} question(s) to {args.out}")
        return 0

    if args.command == "verify":
        from ogr.verify import run as run_verify

        return run_verify(pre_build=args.pre_build)

    if args.command == "coverage":

        from ogr.ingest.infobox import parse_corpus

        _, report = parse_corpus(args.corpus)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report.as_markdown(), encoding="utf-8")
        print(f"Wrote {out_path} ({report.olympic_events}/{report.total_documents} Olympic events)")
        return 0

    if args.command == "batch":
        import time
        from datetime import UTC, datetime

        from ogr.common.llm import LLMRateLimitError
        from ogr.common.trials import TrialLog
        from ogr.eval.batch_runner import (
            BatchIncompleteError,
            default_pipelines,
            effective_pool_size,
            run_batch_sync,
            run_config_header,
        )

        config = _query_config(args.embedding_model)
        if config is None:
            return 1
        if args.mode:
            config = config.model_copy(update={"latency_mode": args.mode})
        client = TigerGraphClient(config)
        started = datetime.now(UTC)
        run_id = args.run_id or started.strftime("%Y%m%dT%H%M%SZ")
        dataset = Path(args.questions).stem
        # The app lists a run from out/<run_id>.jsonl only.
        app_path = OUT_DIR / f"{run_id}.jsonl"
        if Path(args.out).resolve() != app_path.resolve():
            print(f"Note: the app's Dashboard and Eval table read {app_path}; this run is written to "
                  f"{args.out} and will not show there.", file=sys.stderr)
        started_clock = time.monotonic()

        def record_trial(status: str, questions: int | None = None, error: Exception | None = None) -> None:
            # The entry POST /batch writes, so a CLI run shows on the History screen too.
            TrialLog(OUT_DIR / "history.jsonl").append(
                "benchmark", status, subject=f"{dataset} · {run_id}", run_id=run_id, dataset=dataset,
                questions=questions, duration_ms=round((time.monotonic() - started_clock) * 1000),
                error=str(error)[:500] if error else None, llm_provider=config.llm_provider,
                llm_model=config.llm_model, embedding_model=config.embedding_model,
            )

        try:
            count = run_batch_sync(
                questions_path=args.questions,
                out_path=args.out,
                pipelines=default_pipelines(config, client),
                run_id=run_id,
                run_config={
                    **run_config_header(config),
                    "dataset": dataset,
                    "started_at": started.isoformat(),
                },
                pool_size=effective_pool_size(config),
                max_total_tokens=config.max_total_tokens,
            )
        except BatchIncompleteError as e:
            record_trial("error", error=e)
            print(f"Batch {run_id} incomplete: {e}", file=sys.stderr)
            return 1
        except LLMRateLimitError as e:
            record_trial("error", error=e)
            print(f"Batch {run_id} stopped: {e}", file=sys.stderr)
            return 1
        record_trial("complete", questions=count)
        print(f"Batch {run_id}: ran {count} question(s), wrote to {args.out}")
        return 0

    if args.command == "build":
        return _build(args.corpus, args.vector_timeout)

    if args.command == "ask":
        requested_pipelines = [p.strip().lower() for p in args.pipelines.split(",")]
        config = _query_config(args.embedding_model)
        if config is None:
            return 1
        client = TigerGraphClient(config)

        from ogr.eval.dispatcher import error_record
        from ogr.pipelines.p2_graphrag import run_p2_graphrag
        from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic

        runners = {
            "rag": ("rag", lambda: run_p1_rag(query=args.query, client=client, config=config)),
            "graphrag": ("graphrag", lambda: run_p2_graphrag(query=args.query, client=client, config=config)),
            "agentic_graphrag": (
                "agentic_graphrag",
                lambda: run_p3_agentic(query=args.query, tg_client=client, config=config),
            ),
        }
        runners["graph"] = runners["graphrag"]
        runners["agentic"] = runners["agentic_graphrag"]

        unknown = [p for p in requested_pipelines if p not in runners]
        if unknown:
            print(f"Unknown pipeline(s): {', '.join(unknown)}; choose from {', '.join(sorted(runners))}",
                  file=sys.stderr)
            return 2
        records = {}
        for p in requested_pipelines:
            name, run = runners[p]
            # Same fault isolation as dispatcher.py / api/main.py: one
            # pipeline's exception must not discard the others' output.
            try:
                records[name] = run()
            except Exception as e:  # noqa: BLE001
                records[name] = error_record(name, str(e))

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
