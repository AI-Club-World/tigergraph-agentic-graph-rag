"""Tests for the streaming trace emitter.

trace.py is built on LangGraph `astream_events`, so the same generator serves
both the live SSE trace panel and the collected `trace` array in the batch
record. **One emitter, two consumers** — assembling the trace twice is how the
demo and the submitted metrics drift apart (AD-1, AD-2).

The load-bearing assertion here is the last one: what the stream emits and what
the record carries must be the same steps, not two independently-built lists.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.common.contracts import PipelineRecord, TraceStep
from ogr.graph.client import TigerGraphClient
from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker
from ogr.pipelines.p3_agentic.orchestrator import astream_p3_agentic, run_p3_agentic

CHUNKS = [
    {
        "chunk_id": f"Q1_c{i}",
        "doc_id": "Q1",
        "text": "United States won the most gold medals in athletics in 2008",
        "vtype": "Chunk",
    }
    for i in range(3)
]

QUESTION = "Which nation won the most golds at the Games before the 2012 Summer Olympics?"


def _mock_llm() -> MagicMock:
    model = MagicMock()

    def invoke(messages, **_kwargs):
        response = MagicMock()
        response.tool_calls = []
        response.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        response.response_metadata = {}
        text = " ".join(str(getattr(m, "content", "")) for m in messages).lower()
        if "intent parser" in text:
            response.content = json.dumps({
                "operation": "TRAVERSE",
                "anchor": {"games": "2012-Summer"},
                "target_field": "gold",
                "constraints": [],
            })
        elif "groundedness" in text:
            response.content = "YES"
        else:
            response.content = json.dumps({"answer": "United States", "explanation": "e"})
        return response

    model.invoke.side_effect = invoke
    model.bind_tools.return_value = model
    return model


def _collect():
    """Run the stream to completion, returning (steps, record)."""
    config = RunConfig()

    async def run():
        steps, record = [], None
        async for item in astream_p3_agentic(
            QUESTION,
            llm_model=_mock_llm(),
            tg_client=TigerGraphClient(config=config, mock_chunks=CHUNKS),
            entity_linker=EntityLinker(games_vocab=["2012-Summer", "2008-Summer"]),
            config=config,
        ):
            if isinstance(item, TraceStep):
                steps.append(item)
            else:
                record = item
        return steps, record

    return asyncio.run(run())


def test_stream_yields_trace_steps_then_the_record():
    steps, record = _collect()

    assert steps, "The stream produced no TraceStep"
    assert isinstance(record, PipelineRecord)
    assert record.status == "done"


def test_step_numbers_are_sequential():
    steps, _ = _collect()
    assert [s.step_n for s in steps] == list(range(1, len(steps) + 1))


def test_one_emitter_two_consumers():
    """The streamed steps and the record's trace array must be the same steps."""
    steps, record = _collect()

    streamed = [(s.step_n, s.agent_type, s.tool_called, s.tokens.total) for s in steps]
    collected = [
        (s.step_n, s.agent_type, s.tool_called, s.tokens.total) for s in (record.trace or [])
    ]
    assert streamed == collected, (
        "The live stream and the batch record disagree — the trace is being "
        "assembled twice (AD-1, AD-2)."
    )


def test_stream_matches_the_sync_run():
    """Streaming must not change the answer, the stop reason or the cost."""
    streamed_steps, streamed_record = _collect()

    config = RunConfig()
    sync_record = run_p3_agentic(
        QUESTION,
        llm_model=_mock_llm(),
        tg_client=TigerGraphClient(config=config, mock_chunks=CHUNKS),
        entity_linker=EntityLinker(games_vocab=["2012-Summer", "2008-Summer"]),
        config=config,
    )

    assert streamed_record.answer == sync_record.answer
    assert streamed_record.stop_reason == sync_record.stop_reason
    assert streamed_record.tokens.total == sync_record.tokens.total
    assert len(streamed_steps) == len(sync_record.trace or [])


def test_streamed_record_reconciles():
    """The token-reconciliation guard holds on the streamed record too."""
    _, record = _collect()
    step_sum = sum(s.tokens.total for s in (record.trace or []))
    assert step_sum == record.tokens.total
