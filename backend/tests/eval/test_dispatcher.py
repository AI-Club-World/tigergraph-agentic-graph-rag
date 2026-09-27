"""Tests for EVAL-03 dispatch.

The concurrency test is the one that matters most: the manual check is
"if the three columns appear together, the dispatcher is serialising and NFR-1
is unmet regardless of what the code looks like". This asserts that in code.
"""

from __future__ import annotations

import asyncio
import time

from ogr.common.contracts import Citation, PipelineRecord, TokenUsage
from ogr.eval.dispatcher import PIPELINE_IDS, dispatch, dispatch_sync


def _record(pipeline: str, answer: str = "26", total: int = 100) -> PipelineRecord:
    return PipelineRecord(
        pipeline=pipeline,  # type: ignore[arg-type]
        answer=answer,
        explanation="e",
        citations=[Citation(source_id="Q1", chunk_id=None, ref_type="entity")],
        chunks_returned=1,
        citations_count=1,
        tokens=TokenUsage(input=total - 10, output=10, total=total),
    )


def _ok(pipeline: str):
    return lambda _query: _record(pipeline)


def _boom(_query):
    raise RuntimeError("provider exploded")


class TestFaultIsolation:
    """test_one_pipeline_error_does_not_block_others (NFR-2)."""

    def test_one_failure_does_not_block_the_others(self):
        records = dispatch_sync("q", {
            "rag": _ok("rag"),
            "graphrag": _boom,
            "agentic_graphrag": _ok("agentic_graphrag"),
        })

        assert set(records) == set(PIPELINE_IDS)
        assert records["rag"].status == "done"
        assert records["agentic_graphrag"].status == "done"
        assert records["graphrag"].status == "error"
        assert "provider exploded" in records["graphrag"].error_detail

    def test_dispatcher_never_raises(self):
        """In batch mode one bad question must not halt a 100-question run."""
        records = dispatch_sync("q", {p: _boom for p in PIPELINE_IDS})
        assert all(r.status == "error" for r in records.values())

    def test_a_failed_pipeline_still_conforms_to_the_record_contract(self):
        records = dispatch_sync("q", {"rag": _boom})
        record = records["rag"]
        assert isinstance(record, PipelineRecord)
        assert record.pipeline == "rag"
        assert record.tokens.total == 0
        assert record.answer == ""

    def test_a_pipeline_returning_the_wrong_type_is_an_error_not_a_crash(self):
        records = dispatch_sync("q", {"rag": lambda _q: {"answer": "26"}})
        assert records["rag"].status == "error"
        assert "expected PipelineRecord" in records["rag"].error_detail


class TestConcurrency:
    """NFR-1: concurrent, not sequential."""

    def test_pipelines_run_concurrently(self):
        delay = 0.3

        def slow(pipeline: str):
            def run(_query):
                time.sleep(delay)
                return _record(pipeline)
            return run

        started = time.perf_counter()
        records = dispatch_sync("q", {p: slow(p) for p in PIPELINE_IDS})
        elapsed = time.perf_counter() - started

        assert len(records) == 3
        assert elapsed < delay * 2, (
            f"Three {delay}s pipelines took {elapsed:.2f}s. Serial execution would "
            "take ~3x; the dispatcher is not running them concurrently (NFR-1)."
        )

    def test_a_blocking_sync_pipeline_does_not_stall_the_others(self):
        """A sync pipeline must not monopolise the event loop."""
        async def fast(_query):
            return _record("graphrag")

        def blocking(_query):
            time.sleep(0.3)
            return _record("rag")

        started = time.perf_counter()
        records = dispatch_sync("q", {"rag": blocking, "graphrag": fast})
        elapsed = time.perf_counter() - started

        assert records["graphrag"].status == "done"
        assert elapsed < 0.6


class TestAsyncPipelines:
    def test_async_and_sync_pipelines_mix(self):
        async def async_pipeline(_query):
            await asyncio.sleep(0)
            return _record("agentic_graphrag")

        records = dispatch_sync("q", {
            "rag": _ok("rag"),
            "agentic_graphrag": async_pipeline,
        })
        assert all(r.status == "done" for r in records.values())

    def test_dispatch_is_awaitable_directly(self):
        records = asyncio.run(dispatch("q", {"rag": _ok("rag")}))
        assert records["rag"].status == "done"

    def test_empty_pipeline_map(self):
        assert dispatch_sync("q", {}) == {}
