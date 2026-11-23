"""`r2-run`: answer a questions file, one answer line per question, written as each finishes.

Sequential by default (determinism, clean query-log timestamps); `workers` > 1 runs questions in
threads and writes lines in completion order. A rerun skips qids already in the output file.
The `local` backend (LocalR2Graph over the corpus) is DEV ONLY: its tool steps carry
`tigergraph: false`, so a file made with it can never pass as a submission.
"""

from __future__ import annotations

import json
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ogr.common.config import RunConfig, get_default_config
from ogr.common.llm import get_chat_model
from ogr.r2.agent import answer_question
from ogr.r2.graph_backend import R2Graph
from ogr.r2.output import AnswerRecord
from ogr.r2.querylog import QueryLog

__all__ = ["make_model", "make_graph", "run_questions", "read_questions", "done_qids"]

MIN_ANSWER_TOKENS = 4096  # a JSON list answer must not be cut off by the Round-1 default of 1024


def make_model(config: RunConfig) -> Any:
    """The chat model for a run (the seam tests replace): temperature and provider from config,
    with room for a long finish payload."""
    if config.llm_max_tokens < MIN_ANSWER_TOKENS:
        config = config.model_copy(update={"llm_max_tokens": MIN_ANSWER_TOKENS})
    return get_chat_model(config)


def make_graph(backend: str, corpus: str | Path, config: RunConfig) -> R2Graph:
    if backend == "local":
        from ogr.r2.corpus_model import build_model
        from ogr.r2.local_graph import LocalR2Graph

        return LocalR2Graph(build_model(corpus))
    from ogr.graph.client import TigerGraphClient
    from ogr.r2.graph_backend import TigerGraphR2

    return TigerGraphR2(TigerGraphClient(config))


def read_questions(path: str | Path) -> list[dict]:
    rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("qid") and r.get("question")]


def done_qids(path: str | Path) -> set[str]:
    p = Path(path)
    if not p.exists():
        return set()
    out = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.add(json.loads(line)["qid"])
        except (ValueError, KeyError, TypeError):
            continue
    return out


def run_questions(questions: list[dict], out: str | Path, graph: R2Graph, model: Any,
                  config: RunConfig | None = None, *, querylog: QueryLog | None = None, workers: int = 1,
                  on_record: Callable[[AnswerRecord], None] | None = None) -> dict[str, Any]:
    """Answer every question not already in `out`; return a summary dict."""
    config = config or get_default_config()
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    skip = done_qids(out)
    todo = [q for q in questions if q["qid"] not in skip]
    lock = threading.Lock()
    statuses: Counter[str] = Counter()
    tokens = [0, 0]
    failed: list[str] = []

    def one(q: dict) -> None:
        rec = answer_question(q["qid"], q["question"], graph, model, config, querylog=querylog)
        with lock:
            if rec.error:
                # Not written: the next run (resume) retries it.
                failed.append(f"{rec.qid}: {rec.error}")
                return
            with out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
            statuses[rec.status] += 1
            tokens[0] += rec.input_tokens
            tokens[1] += rec.output_tokens
        if on_record:
            on_record(rec)

    t0 = time.perf_counter()
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, todo))
    else:
        for q in todo:
            one(q)
    return {"answered_now": len(todo) - len(failed), "failed": failed,
            "skipped": len(questions) - len(todo), "statuses": dict(statuses),
            "input_tokens": tokens[0], "output_tokens": tokens[1],
            "seconds": round(time.perf_counter() - t0, 1)}


def new_run_id() -> str:
    return datetime.now(UTC).strftime("r2-%Y%m%dT%H%M%SZ")
