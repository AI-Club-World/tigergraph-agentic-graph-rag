"""Query Dispatcher — fires all three pipelines concurrently.

Source spec: ARCHITECTURE-SPEC §2, §10 · Plan: implementation-plan-UI.md Group 2 (EVAL-03)
Requirement: FR-2, NFR-1, NFR-2 · Gate: G2

NFR-1: the three pipelines run concurrently, not sequentially. A cost/time
comparison is only meaningful if latency is not inflated by serial waits, and
the demo's "three columns populate at visibly different times" depends on it.

NFR-2: failure or timeout in one pipeline must not block the other two. Every
pipeline call is wrapped independently and a failure yields a PipelineRecord
with status="error" — this module never raises to its caller, because in batch
mode one bad question must not halt a 100-question run. Sole exception:
LLMRateLimitError (DP-3) — every later call would fail the same way, so the
run stops and the user switches model.

AD-1: this is the single dispatch implementation, used by both the interactive
API and the batch runner, so demo behaviour and submitted metrics cannot drift.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

from ogr.common.contracts import PipelineRecord, TokenUsage
from ogr.common.llm import LLMRateLimitError

logger = logging.getLogger(__name__)

__all__ = ["PIPELINE_IDS", "dispatch", "dispatch_sync", "error_record"]

PIPELINE_IDS: tuple[str, str, str] = ("rag", "graphrag", "agentic_graphrag")


def error_record(pipeline: str, detail: str, latency_ms: float = 0.0) -> PipelineRecord:
    """The record a failed pipeline contributes, so the other two still render."""
    return PipelineRecord(
        pipeline=pipeline,  # type: ignore[arg-type]
        answer="",
        explanation=f"Pipeline failed: {detail}",
        citations=[],
        chunks_returned=0,
        citations_count=0,
        tokens=TokenUsage(),
        token_source="provider",
        latency_ms=latency_ms,
        trace=None,
        strategy_changed=None,
        stop_reason=None,
        status="error",
        error_detail=detail,
    )


async def _run_one(pipeline: str, fn: Callable[[str], Any], query: str) -> PipelineRecord:
    """Invoke one pipeline in its own failure domain.

    Sync pipelines are pushed to a worker thread so a blocking call in one of
    them cannot stall the event loop and serialise the other two — which would
    silently violate NFR-1 while still looking concurrent.
    """
    started = time.perf_counter()
    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(query)
        else:
            result = await asyncio.to_thread(fn, query)
    except LLMRateLimitError:
        raise  # DP-3: a rate-limited model stops the whole run, not one record
    except Exception as e:  # noqa: BLE001 - fault isolation is the point
        latency_ms = (time.perf_counter() - started) * 1000.0
        logger.error("Pipeline %s failed: %s", pipeline, e)
        return error_record(pipeline, str(e), latency_ms)

    if not isinstance(result, PipelineRecord):
        latency_ms = (time.perf_counter() - started) * 1000.0
        detail = f"{pipeline} returned {type(result).__name__}, expected PipelineRecord"
        logger.error("%s", detail)
        return error_record(pipeline, detail, latency_ms)

    return result


async def dispatch(
    query: str,
    pipelines: Mapping[str, Callable[[str], Any]],
) -> dict[str, PipelineRecord]:
    """Run every supplied pipeline concurrently and return one record each.

    Args:
        query: the question text, passed identically to each pipeline.
        pipelines: {pipeline_id: callable}. Sync or async callables both work.

    A pipeline that fails contributes an error record instead; the one
    exception is LLMRateLimitError, which stops the whole run (DP-3).
    """
    if not pipelines:
        return {}

    names = list(pipelines)
    records = await asyncio.gather(
        *(_run_one(name, pipelines[name], query) for name in names)
    )
    return dict(zip(names, records, strict=True))


def dispatch_sync(
    query: str,
    pipelines: Mapping[str, Callable[[str], Any]],
) -> dict[str, PipelineRecord]:
    """Blocking wrapper for the CLI and other non-async callers."""
    return asyncio.run(dispatch(query, pipelines))
