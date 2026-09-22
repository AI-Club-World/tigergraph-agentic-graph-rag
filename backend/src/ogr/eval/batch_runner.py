"""Batch runner (EVAL-04) — runs a JSONL question set through all supplied
pipelines and appends one BatchRecord per question to a BatchStore.

Source spec: TECHNICAL-SPEC §4.3, §6.4 · implementation-plan-UI.md Group 5 (EVAL-04)
Requirement: FR-13, FR-15, NFR-4 · Gate: G5, G6

This is the piece that turns EVAL-02/EVAL-03's unit-tested-in-isolation
scorer/dispatcher/aggregator into the actual per-pipeline accuracy and token
numbers the submission is scored on — nothing else in the repo loops over an
eval file end to end.

Resume: `question_id`s already present in the output file are skipped, so a
killed run restarts without re-answering completed questions or re-spending
their tokens (DP-3).

Pool: a bounded `asyncio.Semaphore`, not one query at a time and not all of
them at once. PLAT-08 defaults to 2 concurrent on cloud free tiers, because a
429 storm mid-run is the likeliest cause of a partial run; `RunConfig.pool_size`
is the operator's knob on the day.

`acceptance/holdout/eval_hidden.jsonl` is not referenced anywhere in this
module by name — the caller passes whatever `questions_path` it wants. Only
a caller explicitly invoking this against the holdout path (a separate,
one-time `--holdout` invocation per BUILD-PLAN §2) may do so; the CI holdout
grep enforces that no other source file names the path directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from ogr.common.config import RunConfig
from ogr.common.contracts import BatchRecord, Question
from ogr.eval.aggregator import aggregate_query
from ogr.eval.dispatcher import dispatch
from ogr.eval.store import BatchStore, read_written_qids

logger = logging.getLogger(__name__)

__all__ = ["load_questions", "run_batch", "run_batch_sync", "run_config_header"]


def run_config_header(config: RunConfig) -> dict[str, Any]:
    """The non-secret subset of RunConfig persisted with every batch run
    (TECHNICAL-SPEC §4.3, §11, §14.3). Deliberately excludes every credential
    field (`llm_api_key`, `tg_password`, `tg_secret`, `tg_token`, `tg_jwt_token`)
    — those never enter a persisted record, so this function builds the header
    from an explicit allow-list rather than dumping the config object.
    """
    return {
        "llm_provider": config.llm_provider,
        "llm_model": config.llm_model,
        "llm_base_url": config.llm_base_url,
        "temperature": config.llm_temperature,
        "embedding_model": config.embedding_model,
        "k": config.k,
        "chunk_tokens": config.chunk_tokens,
        "chunk_overlap": config.chunk_overlap,
        "max_steps": config.max_steps,
        "max_tokens_per_query": config.max_tokens_per_query,
        "pool_size": config.pool_size,
    }


def load_questions(path: str | Path) -> list[Question]:
    """Parse a JSONL question file (eval_public.jsonl / eval_hidden.jsonl shape)."""
    questions: list[Question] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            questions.append(Question(**json.loads(line)))
    return questions


async def run_batch(
    questions_path: str | Path,
    out_path: str | Path,
    pipelines: Mapping[str, Callable[[str], Any]],
    run_id: str,
    run_config: dict[str, Any],
    pool_size: int = 2,
) -> int:
    """Run every question in `questions_path` not already in `out_path`.

    Returns the number of questions actually run (0 if the file was already
    complete). Never raises on a per-question failure — `dispatch()` already
    turns a pipeline exception into an error record, and one question's
    failure must not halt the rest of a 100-question run (NFR-2).
    """
    questions = load_questions(questions_path)
    already_written = read_written_qids(out_path)
    pending = [q for q in questions if q.qid not in already_written]
    if not pending:
        return 0

    store = BatchStore(out_path, run_config)
    semaphore = asyncio.Semaphore(max(1, pool_size))
    write_lock = asyncio.Lock()

    async def _run_one(question: Question) -> None:
        async with semaphore:
            records = await dispatch(question.question, pipelines)

        query_record = aggregate_query(
            query_id=question.qid,
            query_text=question.question,
            records=records,
            gold_variants=question.answer or None,
            qtype=question.qtype,
        )
        batch_record = BatchRecord(
            run_id=run_id,
            question_id=question.qid,
            question_text=question.question,
            qtype=question.qtype,
            ground_truth=question.answer,
            gold_doc_ids=question.gold_doc_ids,
            record=query_record,
        )
        async with write_lock:
            store.append(batch_record.model_dump())

    await asyncio.gather(*(_run_one(q) for q in pending))
    return len(pending)


def run_batch_sync(
    questions_path: str | Path,
    out_path: str | Path,
    pipelines: Mapping[str, Callable[[str], Any]],
    run_id: str,
    run_config: dict[str, Any],
    pool_size: int = 2,
) -> int:
    """Blocking wrapper for the CLI and other non-async callers."""
    return asyncio.run(
        run_batch(questions_path, out_path, pipelines, run_id, run_config, pool_size)
    )
