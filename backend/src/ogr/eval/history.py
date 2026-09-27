"""Benchmark history — every batch run in `out/*.jsonl` is one history entry.

No database: the append-only JSONL store (`store.py`) already is the history.
This module reads it back as run summaries (config metadata plus per-pipeline
accuracy, tokens, latency and efficiency), serves scored records for the
dashboard drill-down, and imports previously executed runs from JSON.

Scores come from `scorer.py` — the one scoring implementation (NFR-5, NFR-6).
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ogr.eval.scorer import grounding, score_answer
from ogr.eval.store import BatchStore, _assert_no_secret, iter_lines

__all__ = ["RUN_ID_RE", "import_run", "is_run_id", "list_runs", "read_run", "summarize_run", "view_record"]

logger = logging.getLogger(__name__)

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
# `out/` also holds the server's own state; a run may never take those names
# (a run called `history` would share its file with the trial log).
RESERVED_RUN_IDS = frozenset({"history", "chunks", "datasets", "embeddings"})


def is_run_id(run_id: object) -> bool:
    if not isinstance(run_id, str) or not RUN_ID_RE.match(run_id):
        return False
    return run_id.lower() not in RESERVED_RUN_IDS


PIPELINE_ORDER = ("rag", "graphrag", "agentic_graphrag")


def _is_run_file(path: Path) -> bool:
    """Only files whose first line is a run_config header are runs — `out/`
    also holds ingest artefacts such as `chunks.jsonl`."""
    try:
        with path.open(encoding="utf-8") as handle:
            first = json.loads(handle.readline() or "null")
    except (OSError, ValueError):
        return False
    return isinstance(first, dict) and "run_config" in first


def read_run(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(run_config, records) from one run file. When a question was run
    again (a resume retrying an errored question), its last record wins."""
    run_config: dict[str, Any] = {}
    by_question: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for i, data in enumerate(iter_lines(path)):
        if i == 0 and "run_config" in data:
            run_config = data["run_config"]
        elif data.get("question_id"):
            by_question.pop(data["question_id"], None)  # keep file order of the latest
            by_question[data["question_id"]] = data
        else:
            unkeyed.append(data)
    return run_config, [*by_question.values(), *unkeyed]


def _score(record: dict[str, Any]) -> dict[str, Any] | None:
    gold = record.get("ground_truth") or []
    if not gold:
        return None
    return {
        name: score_answer(
            prediction=pipeline.get("answer") or "",
            gold_variants=gold,
            retrieved_doc_ids=[c.get("source_id", "") for c in pipeline.get("citations") or []],
            gold_doc_ids=record.get("gold_doc_ids") or [],
            evidence_texts=[c.get("snippet") or "" for c in pipeline.get("citations") or []],
        ).model_dump()
        for name, pipeline in record["record"]["pipelines"].items()
    }


def _grounding(record: dict[str, Any]) -> dict[str, float]:
    """Grounding per pipeline — needs no gold, so it covers the hidden set."""
    return {
        name: grounding(
            pipeline.get("answer") or "", [c.get("snippet") or "" for c in pipeline.get("citations") or []]
        )
        for name, pipeline in (record.get("record") or {}).get("pipelines", {}).items()
    }


def view_record(record: dict[str, Any]) -> dict[str, Any]:
    """A stored record in the shape the dashboard reads: `qid`/`question`
    field names and backend-computed `scores` (null without ground truth)."""
    view = dict(record)
    view.setdefault("qid", record.get("question_id", ""))
    view.setdefault("question", record.get("question_text", ""))
    # Always computed here, never taken from the file: an imported run
    # cannot bring its own scores.
    view["scores"] = _score(record)
    view["grounding"] = _grounding(record)
    return view


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_run(
    run_id: str, run_config: dict[str, Any], records: list[dict[str, Any]], status: str = "complete"
) -> dict[str, Any]:
    views = [view_record(r) for r in records]
    present = {name for v in views for name in v["record"]["pipelines"]}
    names = [p for p in PIPELINE_ORDER if p in present] + sorted(present - set(PIPELINE_ORDER))

    pipelines: dict[str, Any] = {}
    for name in names:
        runs = [v["record"]["pipelines"][name] for v in views if name in v["record"]["pipelines"]]
        scores = [v["scores"][name] for v in views if v["scores"] and name in v["scores"]]
        # Cost and latency are over answered questions only: an error record
        # carries 0 tokens, and averaging it in would make the pipeline that
        # fails most look cheapest. Errors are counted separately.
        answered = [r for r in runs if r.get("status") != "error"]
        tokens = [r["tokens"]["total"] for r in answered]
        mean_tokens = _mean(tokens)
        f1 = _mean([s["f1"] for s in scores])
        pipelines[name] = {
            "em": _mean([s["em"] for s in scores]),
            "f1": f1,
            "precision": _mean([s["precision"] for s in scores]),
            "recall": _mean([s["recall"] for s in scores]),
            "mean_tokens": mean_tokens,
            "median_tokens": statistics.median(tokens) if tokens else None,
            "total_tokens": sum(tokens),
            "mean_latency_ms": _mean([r["latency_ms"] for r in answered]),
            "mean_input_tokens": _mean([r["tokens"].get("input", 0) for r in answered]),
            "mean_output_tokens": _mean([r["tokens"].get("output", 0) for r in answered]),
            "completeness": _mean([s.get("completeness", s["recall"]) for s in scores]),
            "grounded": _mean([
                v["grounding"][name] for v in views
                if name in v["grounding"] and v["record"]["pipelines"][name].get("status") != "error"
            ]),
            "errors": sum(1 for r in runs if r.get("status") == "error"),
            # Accuracy bought per 1k tokens — the cost axis of the thesis.
            "f1_per_1k_tokens": f1 / (mean_tokens / 1000) if f1 is not None and mean_tokens else None,
        }

    timestamps = [v["record"].get("timestamp") for v in views if v["record"].get("timestamp")]
    return {
        "run_id": run_id,
        "status": status,
        "started_at": run_config.get("started_at") or (min(timestamps) if timestamps else None),
        "dataset": run_config.get("dataset"),
        "run_config": run_config,
        "n_questions": len(views),
        "scored": any(v["scores"] for v in views),
        "pipelines": pipelines,
    }


def list_runs(out_dir: Path, statuses: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Every run in `out_dir`, newest first. `statuses` overrides the default
    `complete` for runs this process is still executing (or that failed)."""
    statuses = statuses or {}
    summaries = []
    for path in out_dir.glob("*.jsonl") if out_dir.exists() else []:
        if not is_run_id(path.stem) or not _is_run_file(path):
            continue
        try:
            run_config, records = read_run(path)
            summary = summarize_run(path.stem, run_config, records, statuses.get(path.stem, "complete"))
        except (KeyError, TypeError, ValueError) as e:
            # One malformed file must not take the whole history down.
            logger.warning("Skipping unreadable run %s: %s", path.name, e)
            continue
        if summary["started_at"] is None:
            summary["started_at"] = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
        summaries.append(summary)
    return sorted(summaries, key=lambda s: s["started_at"], reverse=True)


def import_run(out_dir: Path, payload: Any) -> str:
    """Store a previously executed run. Accepts the export shape
    `{run_id?, run_config?, records: [...]}` or a bare list of records.

    Raises ValueError on a malformed payload or unsafe run id, FileExistsError
    if the run id is taken — history is append-only, never overwritten.
    """
    if isinstance(payload, list):
        records, run_config, run_id = payload, {}, None
    elif isinstance(payload, dict):
        records = payload.get("records")
        run_config = payload.get("run_config") or {}
        run_id = payload.get("run_id")
    else:
        raise ValueError("Expected a list of records or an object with a 'records' list")

    if not isinstance(records, list) or not records:
        raise ValueError("No records to import")
    if not all(isinstance(r, dict) and isinstance(r.get("record"), dict) for r in records):
        raise ValueError("Every record needs a 'record' object (a QueryLevelRecord)")
    try:
        # Exactly what GET /runs and the drill-down will do with these records:
        # a record they cannot read is refused here, before anything is written.
        summarize_run("import-check", run_config, [{**r, "record": dict(r["record"])} for r in records])
    except (KeyError, TypeError, ValueError, AttributeError) as e:
        raise ValueError(f"Records are not in the run record shape: {type(e).__name__} {e}") from e
    if not isinstance(run_config, dict):
        raise ValueError("'run_config' must be an object")

    run_id = run_id or records[0].get("run_id") or datetime.now(UTC).strftime("import-%Y%m%dT%H%M%SZ")
    if not is_run_id(run_id):
        raise ValueError(
            f"Invalid run id {run_id!r}: letters, digits, '.', '_' and '-' only, and not "
            f"{', '.join(sorted(RESERVED_RUN_IDS))}"
        )

    path = out_dir / f"{run_id}.jsonl"
    if path.exists():
        raise FileExistsError(f"Run {run_id!r} already exists")

    # Checked before anything is written, so a rejected import leaves no partial file.
    _assert_no_secret([run_config, records])
    store = BatchStore(path, {**run_config, "imported_at": datetime.now(UTC).isoformat()})
    for record in records:
        store.append({**record, "run_id": run_id})
    return run_id
