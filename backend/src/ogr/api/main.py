"""API-01 — the FastAPI service joining backend and frontend.

Source spec: TECHNICAL-SPEC §4, §5 · implementation-plan-UI.md Group 2 (API-01)
Requirement: FR-1, FR-13, TECHNICAL-SPEC §4, §5 · Gate: G3

Routes match exactly what `frontend/src/services/*.ts` already expects
(confirmed against the frontend code, not guessed): `POST /query` -> `202
{query_id, stream_token}`, `GET /query/{id}/stream` (SSE), `GET
/query/{id}/result`, `POST /build` -> `202 {build_id, stream_token}`, `GET
/build/{id}/stream` (SSE), `GET /batch/{run_id}/records`, plus the
unauthenticated `GET /health`. Benchmark history: `GET /datasets`, `POST
/batch` (execute a benchmark), `GET /runs`, `POST /runs/import`.

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
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ogr.api.security import StreamTokenStore, get_config, require_api_key
from ogr.common.config import RunConfig, get_default_config
from ogr.common.contracts import PipelineRecord, QueryLevelRecord
from ogr.eval.aggregator import aggregate_query
from ogr.eval.batch_runner import default_pipelines, effective_pool_size, run_batch, run_config_header
from ogr.eval.dispatcher import error_record
from ogr.eval.history import RUN_ID_RE, import_run, list_runs, read_run, summarize_run, view_record
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

# The frontend runs on a different origin (Vite dev server, or a deployed
# static host) and calls this API directly from the browser — without this,
# every fetch fails at the CORS preflight before X-API-Key is ever checked.
# Origins come from OGR_CORS_ORIGINS (config.py); `allow_credentials=False`
# because auth is a header/query token, not a cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_default_config().ogr_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter(dependencies=[Depends(require_api_key)])

_stream_tokens = StreamTokenStore(ttl_s=get_default_config().ogr_stream_token_ttl_s)
_queries: dict[str, dict[str, Any]] = {}
_builds: dict[str, dict[str, Any]] = {}
# Finished query/build entries kept for result reads; older ones are dropped.
_MAX_RETAINED = 100
# One client for the process: its vocabulary cache and connection are reused
# by every query and batch run instead of being rebuilt per request.
_tg_client: TigerGraphClient | None = None
# Also keeps each background run's task referenced so it is not garbage-collected.
_batch_tasks: dict[str, asyncio.Task] = {}

# Runtime model overrides applied on top of env-var config without a restart.
# Keys match RunConfig field names; updated by PATCH /settings.
_runtime_overrides: dict[str, Any] = {}


def _get_config_with_overrides() -> RunConfig:
    base = get_default_config()
    return base.model_copy(update=_runtime_overrides) if _runtime_overrides else base


# Override the per-route dependency so every existing route automatically
# picks up the runtime overrides without touching each handler.
app.dependency_overrides[get_config] = _get_config_with_overrides

# Resolved relative to this file, not the process CWD — a long-running
# service should not depend on which directory it happened to be started
# from (unlike the CLI, whose defaults already assume the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_PATH = _REPO_ROOT / "data" / "corpus" / "corpus.jsonl"
QUESTIONS_DIR = _REPO_ROOT / "data" / "questions"
OUT_DIR = _REPO_ROOT / "out"


class QueryRequest(BaseModel):
    query: str


class SettingsPatch(BaseModel):
    llm_model: str | None = None
    embedding_model: str | None = None


# Embedding dim is fixed per supported model; unknown models keep current dim.
_EMBEDDING_DIMS: dict[str, int] = {
    "BAAI/bge-small-en-v1.5": 384,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
}


def _get_client(config: RunConfig) -> TigerGraphClient:
    global _tg_client
    if _tg_client is None:
        _tg_client = TigerGraphClient(config)
    return _tg_client


def _evict_finished(store: dict[str, dict[str, Any]]) -> None:
    """Keep `store` bounded: drop the oldest finished entries beyond _MAX_RETAINED."""
    excess = len(store) - _MAX_RETAINED
    if excess <= 0:
        return
    finished = [key for key, entry in store.items() if (task := entry.get("task")) is None or task.done()]
    for key in finished[:excess]:
        del store[key]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# ─────────────────────────────────────────── /settings ──────────────────────


@app.get("/settings")
def get_settings_endpoint() -> dict[str, Any]:
    """Return the current effective model/embedding config. Unauthenticated."""
    cfg = _get_config_with_overrides()
    return {
        "llm_provider": cfg.llm_provider,
        "llm_model": cfg.llm_model,
        "embedding_model": cfg.embedding_model,
        "embedding_dim": cfg.embedding_dim,
    }


@router.patch("/settings")
def patch_settings(body: SettingsPatch) -> dict[str, Any]:
    """Update runtime model/embedding without a server restart."""
    global _tg_client
    if body.llm_model is not None:
        _runtime_overrides["llm_model"] = body.llm_model
        # Clear cached model instance so next request builds a new client.
        try:
            from ogr.common.llm import _MODEL_CACHE, _MODEL_CACHE_LOCK
            with _MODEL_CACHE_LOCK:
                _MODEL_CACHE.clear()
        except Exception:  # noqa: BLE001
            pass
    if body.embedding_model is not None:
        _runtime_overrides["embedding_model"] = body.embedding_model
        dim = _EMBEDDING_DIMS.get(body.embedding_model)
        if dim is not None:
            _runtime_overrides["embedding_dim"] = dim
        # Reset TG client so vocabulary cache isn't stale after a rebuild.
        _tg_client = None
    return {
        "llm_provider": _get_config_with_overrides().llm_provider,
        "llm_model": _get_config_with_overrides().llm_model,
        "embedding_model": _get_config_with_overrides().embedding_model,
        "embedding_dim": _get_config_with_overrides().embedding_dim,
    }


@app.get("/health/status")
async def health_status(config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    """Check TigerGraph and LLM reachability in parallel. Unauthenticated — browser polls this."""
    from ogr.verify import check_llm, check_tigergraph

    def _check_db() -> dict[str, Any]:
        t0 = time.monotonic()
        status, detail = check_tigergraph(config)
        return {"status": "ok" if status == "OK" else status.lower(), "detail": detail, "latency_ms": round((time.monotonic() - t0) * 1000)}

    def _check_llm() -> dict[str, Any]:
        t0 = time.monotonic()
        status, detail = check_llm(config)
        return {"status": "ok" if status == "OK" else status.lower(), "detail": detail, "latency_ms": round((time.monotonic() - t0) * 1000)}

    db_result, llm_result = await asyncio.gather(
        asyncio.to_thread(_check_db),
        asyncio.to_thread(_check_llm),
    )
    return {"db": db_result, "llm": llm_result}


# ---------------------------------------------------------------- /query ---


@router.post("/query", status_code=202)
async def post_query(body: QueryRequest, config: RunConfig = Depends(get_config)) -> dict[str, str]:
    _evict_finished(_queries)
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
    client = _get_client(config)
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
    _evict_finished(_builds)
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
        chunks = await asyncio.to_thread(
            chunk_and_embed_corpus, CORPUS_PATH, config.chunk_tokens, config.chunk_overlap
        )
    except Exception as e:  # noqa: BLE001
        progress.error("chunk_embed", all_pipelines, str(e))
        await queue.put(("done", None))
        return
    progress.finish("chunk_embed", all_pipelines, items_done=len(chunks))
    progress.ready(["rag"], note="chunk+embed done — Q5 must still be installed for a live index")

    client = _get_client(config)
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
            client._vocab_cache.clear()  # the reload may have changed Games/Sport/Venue
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


# ------------------------------------------------------ /batch and /runs ---


class BatchRequest(BaseModel):
    dataset: str
    run_id: str | None = None
    # None = RUN_LATENCY_MODE. 'timing' runs pool 1 for comparable latency.
    latency_mode: Literal["throughput", "timing"] | None = None


def _datasets() -> list[str]:
    return sorted(p.stem for p in QUESTIONS_DIR.glob("*.jsonl")) if QUESTIONS_DIR.exists() else []


def _run_statuses() -> dict[str, str]:
    return {
        run_id: "running" if not task.done() else "failed" if task.exception() else "complete"
        for run_id, task in _batch_tasks.items()
        if not task.cancelled()
    }


@router.get("/datasets")
async def get_datasets() -> list[str]:
    return _datasets()


@router.post("/batch", status_code=202)
async def post_batch(body: BatchRequest, config: RunConfig = Depends(get_config)) -> dict[str, str]:
    """Execute a benchmark over a named question set in `data/questions/`.
    Records append to `out/{run_id}.jsonl`, which makes the run part of the
    history as soon as its first question completes.
    """
    if body.dataset not in _datasets():
        raise HTTPException(status_code=404, detail=f"Unknown dataset {body.dataset!r}")
    started = datetime.now(UTC)
    run_id = body.run_id or started.strftime("%Y%m%dT%H%M%SZ")
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail=f"Invalid run id {run_id!r}")
    out_path = OUT_DIR / f"{run_id}.jsonl"
    if out_path.exists() or run_id in _batch_tasks:
        raise HTTPException(status_code=409, detail=f"Run {run_id!r} already exists")
    if body.latency_mode:
        config = config.model_copy(update={"latency_mode": body.latency_mode})

    run_config = {
        # Off the event loop: the header records the embedding backend, which
        # loads the embedding model on first use.
        **(await asyncio.to_thread(run_config_header, config)),
        "dataset": body.dataset,
        "started_at": started.isoformat(),
    }
    _batch_tasks[run_id] = asyncio.create_task(
        run_batch(
            questions_path=QUESTIONS_DIR / f"{body.dataset}.jsonl",
            out_path=out_path,
            pipelines=default_pipelines(config, _get_client(config)),
            run_id=run_id,
            run_config=run_config,
            pool_size=effective_pool_size(config),
            max_total_tokens=config.max_total_tokens,
        )
    )
    return {"run_id": run_id, "status": "running"}


@router.get("/runs")
async def get_runs() -> list[dict[str, Any]]:
    """Benchmark history: one summary per stored run, newest first."""
    return await asyncio.to_thread(list_runs, OUT_DIR, _run_statuses())


@router.post("/runs/import", status_code=201)
async def post_run_import(payload: Any = Body(...)) -> dict[str, Any]:
    """Store a previously executed run from its JSON export."""
    try:
        run_id = import_run(OUT_DIR, payload)
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    run_config, records = read_run(OUT_DIR / f"{run_id}.jsonl")
    return summarize_run(run_id, run_config, records)


@router.get("/batch/{run_id}/records")
async def get_batch_records(run_id: str) -> list[dict[str, Any]]:
    """Reads `out/{run_id}.jsonl` written by EVAL-04's batch runner, as the
    scored view records the dashboard and eval table consume.
    """
    path = OUT_DIR / f"{run_id}.jsonl"
    if not RUN_ID_RE.match(run_id) or not path.exists():
        raise HTTPException(status_code=404, detail=f"No run {run_id!r}")
    _run_config, records = read_run(path)
    return [view_record(r) for r in records]


app.include_router(router)
