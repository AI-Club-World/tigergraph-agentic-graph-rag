"""API-01 — the FastAPI service joining backend and frontend.

Source spec: TECHNICAL-SPEC §4, §5 · implementation-plan-UI.md Group 2 (API-01)
Requirement: FR-1, FR-13, TECHNICAL-SPEC §4, §5 · Gate: G3

Routes match exactly what `frontend/src/services/*.ts` already expects
(confirmed against the frontend code, not guessed): `POST /query` -> `202
{query_id, stream_token}`, `GET /query/{id}/stream` (SSE), `GET
/query/{id}/result`, `POST /build` -> `202 {build_id, stream_token}`, `GET
/build/{id}/stream` (SSE), `GET /batch/{run_id}/records`, plus the
unauthenticated `GET /health`.

`X-API-Key` is a router-level dependency (`require_api_key`), so a new route
is protected by default rather than by someone remembering. The two SSE
routes cannot carry that header (browser `EventSource` is header-less), so
they take a short-lived, single-use `?token=` instead (DP-8).

State is a module-level in-memory dict — this is a single-process demo tool
(BUILD-PLAN §3), not a multi-worker service; a restart loses in-flight query
state, which is an accepted trade-off for something meant to be run once per
demo/benchmark session, not deployed behind a load balancer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ogr.api.security import StreamTokenStore, get_config, require_api_key
from ogr.common.config import RunConfig
from ogr.common.contracts import PipelineRecord, QueryLevelRecord
from ogr.eval.aggregator import aggregate_query
from ogr.eval.dispatcher import error_record
from ogr.graph.client import TigerGraphClient
from ogr.ingest.chunk_embed import chunk_and_embed_corpus
from ogr.ingest.infobox import parse_corpus
from ogr.ingest.load import load_graph
from ogr.ingest.progress import BuildEvent, BuildProgress
from ogr.pipelines.p1_rag import run_p1_rag
from ogr.pipelines.p2_graphrag import run_p2_graphrag
from ogr.pipelines.p3_agentic.orchestrator import astream_p3_agentic

logger = logging.getLogger(__name__)

app = FastAPI(title="OGR API")
router = APIRouter(dependencies=[Depends(require_api_key)])

_stream_tokens = StreamTokenStore()
_queries: dict[str, dict[str, Any]] = {}
_builds: dict[str, dict[str, Any]] = {}

# Resolved relative to this file, not the process CWD — a long-running
# service should not depend on which directory it happened to be started
# from (unlike the CLI, whose defaults already assume the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_PATH = _REPO_ROOT / "data" / "corpus" / "corpus.jsonl"
OUT_DIR = _REPO_ROOT / "out"


class QueryRequest(BaseModel):
    query: str


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ---------------------------------------------------------------- /query ---


@router.post("/query", status_code=202)
async def post_query(body: QueryRequest, config: RunConfig = Depends(get_config)) -> dict[str, str]:
    query_id = str(uuid.uuid4())
    token = _stream_tokens.issue(query_id)
    queue: asyncio.Queue = asyncio.Queue()
    _queries[query_id] = {"queue": queue, "record": None}
    task = asyncio.create_task(_run_query(query_id, body.query, queue, config))
    _queries[query_id]["task"] = task
    return {"query_id": query_id, "stream_token": token}


async def _run_query(query_id: str, query: str, queue: asyncio.Queue, config: RunConfig) -> None:
    """Runs all three pipelines concurrently (NFR-1), streaming each
    pipeline's record the moment it finishes and every agentic TraceStep as
    it is produced, then the aggregated verdict.
    """
    client = TigerGraphClient(config)
    records: dict[str, PipelineRecord] = {}

    async def _rag() -> None:
        try:
            record = await asyncio.to_thread(run_p1_rag, query=query, client=client, config=config)
        except Exception as e:  # noqa: BLE001 - one pipeline's failure must not sink the others
            logger.error("P1 failed: %s", e)
            record = error_record("rag", str(e))
        records["rag"] = record
        await queue.put(("pipeline", record))

    async def _graphrag() -> None:
        try:
            record = await asyncio.to_thread(
                run_p2_graphrag, query=query, client=client, config=config
            )
        except Exception as e:  # noqa: BLE001
            logger.error("P2 failed: %s", e)
            record = error_record("graphrag", str(e))
        records["graphrag"] = record
        await queue.put(("pipeline", record))

    async def _agentic() -> None:
        record: PipelineRecord | None = None
        try:
            async for item in astream_p3_agentic(query, tg_client=client, config=config):
                if isinstance(item, PipelineRecord):
                    record = item
                else:
                    await queue.put(("trace", item))
        except Exception as e:  # noqa: BLE001
            logger.error("P3 failed: %s", e)
            record = error_record("agentic_graphrag", str(e))
        if record is None:
            record = error_record("agentic_graphrag", "no record produced")
        records["agentic_graphrag"] = record
        await queue.put(("pipeline", record))

    await asyncio.gather(_rag(), _graphrag(), _agentic())

    query_record = aggregate_query(query_id=query_id, query_text=query, records=records)
    _queries[query_id]["record"] = query_record
    await queue.put(("done", None))


@router.get("/query/{query_id}/result")
async def get_query_result(query_id: str) -> dict[str, Any]:
    entry = _queries.get(query_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Unknown query_id")
    record: QueryLevelRecord | None = entry.get("record")
    if record is None:
        raise HTTPException(status_code=409, detail="Query still running")
    return record.model_dump()


@app.get("/query/{query_id}/stream")
async def query_stream(query_id: str, token: str):
    if query_id not in _queries:
        raise HTTPException(status_code=404, detail="Unknown query_id")
    if not _stream_tokens.consume(token, query_id):
        raise HTTPException(status_code=401, detail="Invalid or expired stream token")
    return EventSourceResponse(_stream_events(_queries[query_id]["queue"]))


async def _stream_events(queue: asyncio.Queue):
    while True:
        kind, payload = await queue.get()
        if kind == "done":
            yield {"event": "done", "data": "{}"}
            return
        if kind == "trace":
            yield {"event": "trace", "data": payload.model_dump_json()}
        elif kind == "pipeline":
            yield {"event": "pipeline", "data": payload.model_dump_json()}


# ---------------------------------------------------------------- /build ---


@router.post("/build", status_code=202)
async def post_build(config: RunConfig = Depends(get_config)) -> dict[str, str]:
    build_id = str(uuid.uuid4())
    token = _stream_tokens.issue(build_id)
    queue: asyncio.Queue = asyncio.Queue()
    _builds[build_id] = {"queue": queue}
    task = asyncio.create_task(_run_build(build_id, queue, config))
    _builds[build_id]["task"] = task
    return {"build_id": build_id, "stream_token": token}


async def _run_build(build_id: str, queue: asyncio.Queue, config: RunConfig) -> None:
    """Chunk+embed is real and needs no TigerGraph (AD-6). Schema install
    and load only run if a live connection is reachable; if not, that stage
    reports an error rather than a fabricated success (DP-7: a build column
    states what did not happen, it does not hide it).
    """
    def on_event(event: BuildEvent) -> None:
        queue.put_nowait(("build", event))

    progress = BuildProgress(on_event=on_event)
    all_pipelines = ["rag", "graphrag", "agentic_graphrag"]

    if not CORPUS_PATH.exists():
        progress.error("chunk_embed", all_pipelines, f"{CORPUS_PATH} not found")
        await queue.put(("done", None))
        return

    progress.start("chunk_embed", all_pipelines)
    try:
        chunks = await asyncio.to_thread(chunk_and_embed_corpus, CORPUS_PATH)
    except Exception as e:  # noqa: BLE001
        progress.error("chunk_embed", all_pipelines, str(e))
        await queue.put(("done", None))
        return
    progress.finish("chunk_embed", all_pipelines, items_done=len(chunks))
    progress.ready(["rag"], note="chunk+embed done — Q5 must still be installed for a live index")

    client = TigerGraphClient(config)
    client._ensure_connection()
    graph_pipelines = ["graphrag", "agentic_graphrag"]
    if client.conn is None:
        progress.error("schema_and_load", graph_pipelines, "TigerGraph unreachable — set TG_HOST")
    else:
        progress.start("schema_and_load", graph_pipelines)
        try:
            from ogr.graph.schema import install_queries, install_schema

            await asyncio.to_thread(install_schema, client)
            docs, _report = await asyncio.to_thread(parse_corpus, CORPUS_PATH)
            await asyncio.to_thread(load_graph, client, docs, chunks)
            await asyncio.to_thread(install_queries, client)
            progress.finish("schema_and_load", graph_pipelines, items_done=len(docs))
            progress.ready(graph_pipelines)
        except Exception as e:  # noqa: BLE001
            progress.error("schema_and_load", graph_pipelines, str(e))

    await queue.put(("done", None))


@app.get("/build/{build_id}/stream")
async def build_stream(build_id: str, token: str):
    if build_id not in _builds:
        raise HTTPException(status_code=404, detail="Unknown build_id")
    if not _stream_tokens.consume(token, build_id):
        raise HTTPException(status_code=401, detail="Invalid or expired stream token")
    return EventSourceResponse(_stream_build_events(_builds[build_id]["queue"]))


async def _stream_build_events(queue: asyncio.Queue):
    while True:
        kind, payload = await queue.get()
        if kind == "done":
            yield {"event": "done", "data": "{}"}
            return
        if kind == "build":
            yield {"event": "build", "data": json.dumps(payload.__dict__)}


# ---------------------------------------------------------------- /batch ---


@router.get("/batch/{run_id}/records")
async def get_batch_records(run_id: str) -> list[dict[str, Any]]:
    """Reads `out/{run_id}.jsonl` written by EVAL-04's batch runner. The
    first line (the run_config header) is not a record and is skipped.
    """
    path = OUT_DIR / f"{run_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No run found at {path}")

    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for i, line in enumerate(handle):
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            if i == 0 and "run_config" in data:
                continue
            records.append(data)
    return records


app.include_router(router)
