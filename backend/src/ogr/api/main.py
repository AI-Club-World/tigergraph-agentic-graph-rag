"""API-01 — the FastAPI service joining backend and frontend.

Source spec: TECHNICAL-SPEC §4, §5
Requirement: FR-1, FR-13, TECHNICAL-SPEC §4, §5 · Gate: G3

Routes match exactly what `frontend/src/services/*.ts` already expects
(confirmed against the frontend code, not guessed): `POST /query` -> `202
{query_id}`, `GET /query/{id}/stream` (SSE), `GET /query/{id}/result`,
`POST /build` -> `202 {build_id}`, `GET /build/{id}/stream` (SSE), `GET
/batch/{run_id}/records`, plus `GET /health`. Benchmark history: `GET /datasets`, `POST
/batch` (execute a benchmark), `GET /runs`, `POST /runs/import`.

The application is open: no sign-in, key or role on any route (owner's
decision). Put it behind a network boundary or a reverse proxy with its own
authentication if it must not be public.

State is a module-level in-memory dict — this is a single-process demo tool,
not a multi-worker service; a restart loses in-flight query
state, which is an accepted trade-off for something meant to be run once per
demo/benchmark session, not deployed behind a load balancer.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ogr.api.security import get_config
from ogr.common.config import RunConfig, get_default_config
from ogr.common.contracts import PipelineRecord, QueryLevelRecord
from ogr.common.embedding_models import (
    EMBEDDING_MODELS,
    MAX_STORED_MODELS,
    EmbeddingModel,
    UnknownEmbeddingModel,
    resolve_model,
)
from ogr.common.trials import TrialLog
from ogr.eval.aggregator import aggregate_query
from ogr.eval.batch_runner import default_pipelines, effective_pool_size, run_batch, run_config_header
from ogr.eval.dispatcher import error_record
from ogr.eval.history import import_run, is_run_id, list_runs, read_run, summarize_run, view_record
from ogr.graph.client import TigerGraphClient
from ogr.ingest import dataset_meta
from ogr.ingest.adopt import adopt_graph
from ogr.ingest.chunk_embed import chunk_and_embed_corpus
from ogr.ingest.embedding_index import EmbeddingStore, SwitchRefused, run_job
from ogr.ingest.infobox import parse_corpus
from ogr.ingest.load import load_graph
from ogr.ingest.progress import BuildEvent, BuildProgress
from ogr.ingest.registry import DatasetRegistry
from ogr.pipelines.p1_rag import run_p1_rag
from ogr.pipelines.p2_graphrag import run_p2_graphrag
from ogr.pipelines.p3_agentic.orchestrator import astream_p3_agentic

logger = logging.getLogger(__name__)

@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    # Adopt a graph built elsewhere off the event loop: the first page load
    # should not wait on TigerGraph (ingest/adopt.py).
    threading.Thread(target=_ensure_adopted, name="adopt-graph", daemon=True).start()
    yield


app = FastAPI(title="OGR API", lifespan=_lifespan)

# The frontend runs on a different origin (Vite dev server, or a deployed
# static host) and calls this API directly from the browser — without this,
# every fetch fails at the CORS preflight. Origins come from OGR_CORS_ORIGINS
# (config.py); no cookies are used, so `allow_credentials=False`.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_default_config().ogr_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()

_queries: dict[str, dict[str, Any]] = {}
_builds: dict[str, dict[str, Any]] = {}
# Finished query/build entries kept for result reads; older ones are dropped.
_MAX_RETAINED = 100
# Time limits for the TigerGraph and embedding health routes; the LLM's is
# configurable (RunConfig.health_llm_timeout_s) because a completion is slow.
HEALTH_DB_TIMEOUT_S = 20.0
HEALTH_EMBEDDING_TIMEOUT_S = 30.0
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
    update = dict(_runtime_overrides)
    # The embedding model in use is the store's active one (set by a switch),
    # with its own dimension; EMBEDDING_MODEL is only the first default.
    active = _embedding_store().active()
    if active in EMBEDDING_MODELS:
        update.update(embedding_model=active, embedding_dim=EMBEDDING_MODELS[active].dim)
    return base.model_copy(update=update) if update else base


# Override the per-route dependency so every existing route automatically
# picks up the runtime overrides without touching each handler.
app.dependency_overrides[get_config] = _get_config_with_overrides

# Resolved relative to this file, not the process CWD — a long-running
# service should not depend on which directory it happened to be started
# from (unlike the CLI, whose defaults already assume the repo root).
_REPO_ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = _REPO_ROOT / "data" / "corpus"
DEFAULT_DATASET = "corpus"
QUESTIONS_DIR = _REPO_ROOT / "data" / "questions"
OUT_DIR = _REPO_ROOT / "out"


class QueryRequest(BaseModel):
    query: str
    # The embedding model to search with (a catalog key); default: the active
    # one. Sent after the user picks a complete model in the mismatch popup.
    embedding_model: str | None = None


class SettingsPatch(BaseModel):
    llm_provider: Literal["gemini", "nvidia_nim", "groq"] | None = None
    llm_model: str | None = None
    # Only an instant switch (the model is complete); anything that needs
    # embedding goes through POST /embeddings/switch and its explicit choice.
    embedding_model: str | None = None


def _trials() -> TrialLog:
    return TrialLog(OUT_DIR / "history.jsonl")


def _model_fields(config: RunConfig) -> dict[str, Any]:
    """Non-secret run identity recorded with every trial."""
    return {
        "llm_provider": config.llm_provider,
        "llm_model": config.llm_model,
        "embedding_model": config.embedding_model,
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


def _provider_preset(cfg: RunConfig) -> str | None:
    """The selectable preset the effective LLM runs on, so the settings panel
    shows who serves the model. The startup config names a client type
    (`openai_compatible`, `google`) rather than a preset: the base URL's host
    — or the native Gemini client — says which provider that is."""
    from urllib.parse import urlparse

    from ogr.common.llm import GOOGLE_PROVIDERS, PROVIDER_PRESETS

    provider = (cfg.llm_provider or "").strip().lower()
    if provider in PROVIDER_PRESETS:
        return provider
    if provider in GOOGLE_PROVIDERS:
        return "gemini"
    host = (urlparse(cfg.llm_base_url or "").hostname or "").lower()
    if not host:
        return None
    for pid, preset in PROVIDER_PRESETS.items():
        preset_host = urlparse(preset["base_url"] or preset["models_url"]).hostname or ""
        if host == preset_host.lower():
            return pid
    return None


def _public_host(url: str | None) -> str | None:
    from urllib.parse import urlparse

    parsed = urlparse(url or "")
    if not parsed.hostname:
        return None
    return f"{parsed.hostname}:{parsed.port}" if parsed.port else parsed.hostname


def _settings_body(cfg: RunConfig) -> dict[str, Any]:
    return {
        "llm_provider": cfg.llm_provider,
        # The preset id serving the model, or None for a provider outside the
        # presets (then `llm_base_host` says where it runs).
        "llm_provider_preset": _provider_preset(cfg),
        # hostname[:port] only — never the userinfo a URL can carry.
        "llm_base_host": _public_host(cfg.llm_base_url),
        "llm_model": cfg.llm_model,
        "embedding_model": cfg.embedding_model,
        "embedding_dim": cfg.embedding_dim,
    }


@app.get("/settings")
def get_settings_endpoint() -> dict[str, Any]:
    """Return the current effective model/embedding config. Unauthenticated."""
    return _settings_body(_get_config_with_overrides())


@router.get("/settings/providers")
def get_providers() -> list[dict[str, Any]]:
    """Selectable LLM providers; `configured` = its API key is set on the server."""
    from ogr.common.llm import PROVIDER_PRESETS

    cfg = get_default_config()
    return [
        {"id": pid, "label": p["label"], "configured": bool(getattr(cfg, p["key_field"]))}
        for pid, p in PROVIDER_PRESETS.items()
    ]


@router.get("/settings/models")
async def get_provider_models(provider: Literal["gemini", "nvidia_nim", "groq"]) -> dict[str, Any]:
    """Live text-model catalog of one provider. NVIDIA is narrowed to the
    models the NGC catalog labels 'Free Endpoint'; `note` explains when that
    filter could not be applied."""
    from ogr.common.llm import PROVIDER_PRESETS, list_models, nvidia_free_endpoints

    config = get_default_config()
    key = getattr(config, PROVIDER_PRESETS[provider]["key_field"])
    try:
        models = await asyncio.to_thread(list_models, provider, key)
    except Exception as e:  # noqa: BLE001 - surfaced to the user, not swallowed
        raise HTTPException(502, f"{provider}: could not list models ({str(e)[:200]})") from e
    note = None
    if provider == "nvidia_nim":
        models, note = await asyncio.to_thread(nvidia_free_endpoints, models, config)
    return {"provider": provider, "models": models, "note": note}


@router.patch("/settings")
async def patch_settings(body: SettingsPatch) -> dict[str, Any]:
    """Update runtime model/embedding without a server restart. The selected
    LLM applies to all three pipelines: each run snapshots config once.
    Everything is validated before anything changes, so a refused request
    leaves the settings as they were."""
    from ogr.common.llm import PROVIDER_PRESETS

    updates: dict[str, Any] = {}
    if body.llm_provider is not None:
        if not body.llm_model:
            raise HTTPException(422, "llm_model is required when changing llm_provider")
        preset = PROVIDER_PRESETS[body.llm_provider]
        key = getattr(get_default_config(), preset["key_field"])
        if not key:
            raise HTTPException(400, f"{preset['key_field'].upper()} is not set on the server")
        updates.update(
            llm_provider=body.llm_provider, llm_base_url=preset["base_url"] or None, llm_api_key=key
        )
    if body.llm_model is not None:
        updates["llm_model"] = body.llm_model
    activate: str | None = None
    if body.embedding_model is not None:
        model = _catalog_model(body.embedding_model)
        if model.key != _get_config_with_overrides().embedding_model:
            _refuse_while_busy()
            complete = await asyncio.to_thread(_embedding_store().complete_models, _corpus_chunk_ids())
            if model.key not in complete:
                raise _conflict(
                    "embedding_switch_required",
                    f"{model.label} has no complete embeddings; switch through POST /embeddings/switch "
                    "and choose to re-embed or keep parallel indices.",
                )
            activate = model.key

    _runtime_overrides.update(updates)
    if "llm_model" in updates:
        # Clear cached model instance so next request builds a new client.
        from ogr.common.llm import _MODEL_CACHE, _MODEL_CACHE_LOCK

        with _MODEL_CACHE_LOCK:
            _MODEL_CACHE.clear()
    if activate:
        _embedding_store().set_active(activate)
    return _settings_body(_get_config_with_overrides())


# ─────────────────────────────────────────── /embeddings ────────────────────
# Embedding model switching (config-docs/EMBEDDING-SWITCHING.md). Every
# refusal is enforced here, whatever state a (possibly stale) UI shows.

_embedding_job: dict[str, Any] = {"task": None}


def _embedding_store() -> EmbeddingStore:
    return EmbeddingStore(OUT_DIR / "embeddings.json")


# Fresh install against a graph built elsewhere: adopt it once (ingest/adopt.py).
_ADOPTION_ENABLED = True
_adoption_done: set[Path] = set()
_adoption_lock = threading.Lock()


def _ensure_adopted() -> None:
    """Write out/datasets.json and out/embeddings.json from the graph when
    this install has neither record of it. Once per state directory; retried
    while TigerGraph is unreachable."""
    if not _ADOPTION_ENABLED or OUT_DIR in _adoption_done:
        return
    with _adoption_lock:
        if OUT_DIR in _adoption_done:
            return
        if _registry().read()["datasets"]:
            _adoption_done.add(OUT_DIR)
            return
        config = _get_config_with_overrides()
        client = _get_client(config)
        client._ensure_connection()
        if client.conn is None:
            return  # TigerGraph not reachable yet: try again on the next call
        try:
            adopt_graph(client, _registry(), _embedding_store(), CORPUS_DIR, config.embedding_model)
        except Exception as e:  # noqa: BLE001 - adoption is best effort; live counts still show
            logger.warning("Could not adopt the existing graph: %s", e)
            return
        _adoption_done.add(OUT_DIR)


def _corpus_chunk_ids() -> set[str]:
    _ensure_adopted()
    return _registry().all_chunk_ids()


def _catalog_model(name: str) -> EmbeddingModel:
    try:
        return resolve_model(name)
    except UnknownEmbeddingModel as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class _Reserved:
    """Stands in for a task between a start request's checks and the moment
    its task exists, so a second request arriving across an await sees the
    slot taken (no two builds or runs racing past the same check)."""

    def done(self) -> bool:
        return False

    def cancelled(self) -> bool:
        return False


def _build_running() -> bool:
    return any("task" in b and not b["task"].done() for b in list(_builds.values()))


def _batch_running() -> bool:
    return any(not t.done() for t in list(_batch_tasks.values()))


def _embedding_job_running() -> bool:
    task = _embedding_job.get("task")
    return task is not None and not task.done()


def _refuse_while_busy() -> None:
    """Switching is refused while an ingestion build, a re-embed job or a
    benchmark run is in progress (a run's config points at the embeddings)."""
    _recover_interrupted_job()
    if _batch_running():
        raise _conflict(
            "batch_running",
            "A benchmark run is in progress; the embedding model cannot change until it ends.",
        )
    if _build_running():
        raise _conflict(
            "build_running", "An ingestion build is running; the embedding model cannot change until it ends."
        )
    if _embedding_job_running():
        raise _conflict("embedding_job_running", "A re-embed job is running; wait for it to finish.")


def _recover_interrupted_job() -> None:
    """A job recorded as running with no task in this process was cut off by
    a restart: record it as failed, so it can be resumed (or replaced)."""
    if not _embedding_job_running():
        _embedding_store().recover_interrupted()


def _embedding_overview(config: RunConfig) -> dict[str, Any]:
    _recover_interrupted_job()
    overview = _embedding_store().overview(_corpus_chunk_ids(), config.embedding_model)
    build = _build_running()
    overview["build_running"] = build
    overview["switch_disabled_reason"] = (
        "An ingestion build is running." if build
        else "A re-embed job is running." if _embedding_job_running()
        else "A benchmark run is in progress." if _batch_running()
        else None
    )
    overview["layout_current"] = _registry().current_layout() or not _registry().exists
    return overview


@router.get("/embeddings")
async def get_embeddings(config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    """Every selectable model with its state for the corpus (complete,
    incomplete, building, failed, not stored), the 2-model cap and the job."""
    return await asyncio.to_thread(_embedding_overview, config)


@router.get("/embeddings/plan")
async def get_embedding_plan(model: str, config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    """What switching to `model` would do right now: the dialog's real state."""
    key = _catalog_model(model).key
    plan = await asyncio.to_thread(_embedding_store().plan, key, _corpus_chunk_ids(), config.embedding_model)
    overview = await asyncio.to_thread(_embedding_overview, config)
    plan["switch_disabled_reason"] = overview["switch_disabled_reason"]
    return plan


class EmbeddingSwitch(BaseModel):
    model: str
    # No default: a model without complete embeddings needs the user's choice.
    mode: Literal["replace", "parallel"] | None = None
    evict: str | None = None


@contextmanager
def _job_slot():
    """Hold the job slot while a job is recorded as running and its task is
    created: a recovery check in a worker thread in between would otherwise
    see "running with no task" and mark the brand-new job failed."""
    _embedding_job["task"] = _Reserved()
    try:
        yield
    except SwitchRefused as e:
        _embedding_job["task"] = None
        raise _conflict(e.code, e.message, **e.extra) from e
    except BaseException:
        _embedding_job["task"] = None
        raise
    if isinstance(_embedding_job["task"], _Reserved):
        _embedding_job["task"] = None  # an instant switch: no job was started


def _start_embedding_job(config: RunConfig) -> None:
    from ogr.common.embeddings import embed_texts, embedding_backend
    from ogr.graph.vector_status import wait_until_ready

    client = _get_client(config)

    def embed(model: EmbeddingModel, texts: list[str]) -> list[list[float]]:
        return embed_texts(texts, model_name=model.key, strict=True)

    def job() -> dict[str, Any]:
        store = _embedding_store()
        result = run_job(
            store,
            client,
            corpus=_corpus_chunk_ids,
            embed=embed,
            wait_ready=lambda: wait_until_ready(config, 600.0, conn=client.conn),
            backend=lambda m: embedding_backend(m.key),
        )
        _trials().append(
            "embedding_job", result.get("status", "error"), subject=result.get("model"),
            mode=result.get("mode"), deleted=result.get("delete"), error=result.get("error"),
            chunks=result.get("chunks_done"),
        )
        return result

    _embedding_job["task"] = asyncio.create_task(asyncio.to_thread(job))


@router.post("/embeddings/switch", status_code=202)
async def post_embedding_switch(
    body: EmbeddingSwitch, config: RunConfig = Depends(get_config)
) -> dict[str, Any]:
    """Switch the embedding model. Complete already → instant. Otherwise the
    body must say how: `replace` deletes the outgoing model's embeddings and
    re-embeds (queries wait for it), `parallel` builds alongside and keeps the
    old model queryable. At the 2-model cap `evict` must name the model to
    delete; that deletion runs before the new model's embedding starts."""
    _refuse_while_busy()
    key = _catalog_model(body.model).key
    if body.evict is not None:
        body.evict = _catalog_model(body.evict).key
    with _job_slot():
        result = _embedding_store().begin_switch(
            key, body.mode, body.evict, _corpus_chunk_ids(), config.embedding_model
        )
        if not result["switched"]:
            _start_embedding_job(config)
    return result


@router.post("/embeddings/resume", status_code=202)
async def post_embedding_resume(config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    """Continue a failed job from its last checkpointed batch."""
    _refuse_while_busy()
    with _job_slot():
        job = _embedding_store().begin_resume()
        _start_embedding_job(config)
    return {"job": job}


@router.post("/embeddings/{model}/complete", status_code=202)
async def post_embedding_complete(model: str, config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    """Embed the chunks a stored model is missing (a dataset built while it
    was not the active model)."""
    _refuse_while_busy()
    key = _catalog_model(model).key
    with _job_slot():
        job = _embedding_store().begin_complete(key, _corpus_chunk_ids())
        _start_embedding_job(config)
    return {"job": job}


def _query_config(config: RunConfig, requested: str | None) -> RunConfig:
    """The config a query or batch runs with — or a refusal. The selected
    model must have complete embeddings; the check is by model identity, so
    two 1024-dim models are never treated as interchangeable. There is no
    fallback to another model: the caller must name one it was offered."""
    model = _catalog_model(requested) if requested else resolve_model(config.embedding_model)
    _recover_interrupted_job()
    store = _embedding_store()
    corpus = _corpus_chunk_ids()
    status = store.model_status(model.key, corpus)
    if not status["complete"]:
        available = [EMBEDDING_MODELS[k].public() for k in store.complete_models(corpus)]
        why = {
            "not_stored": "has no embeddings for this data",
            "building": "is still being embedded",
            "failed": "has an incomplete (failed) embedding job",
            "incomplete": f"covers only {status['chunks_done']} of {status['chunks_total']} chunks",
            "evicting": "is being evicted",
        }.get(status["state"], "has no complete embeddings for this data")
        raise _conflict(
            "embedding_mismatch",
            f"The selected embedding model {model.label} {why}; a query cannot be searched against "
            "another model's embeddings.",
            selected=status,
            available=available,
        )
    return config.model_copy(update={"embedding_model": model.key, "embedding_dim": model.dim})


# The health routes are unauthenticated (the browser polls them), so each
# check runs at most once per HEALTH_CACHE_S and never twice at once: a burst
# of requests cannot spend the LLM quota or fill the worker thread pool.
HEALTH_CACHE_S = 30.0
_health_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_health_inflight: dict[str, asyncio.Future] = {}
_URL_USERINFO = re.compile(r"(\w+://)[^/\s@]+@")


def _redact(detail: str, config: RunConfig) -> str:
    """No endpoint URL or credential in an unauthenticated response."""
    for value in (config.tg_host, config.llm_base_url):
        if value:
            detail = detail.replace(value.rstrip("/"), "<host>")
    return _URL_USERINFO.sub(r"\1***@", detail)


async def _timed_check(name: str, timeout_s: float, check, config: RunConfig, *args) -> dict[str, Any]:
    cached = _health_cache.get(name)
    if cached and time.monotonic() - cached[0] < HEALTH_CACHE_S:
        return cached[1]
    if name in _health_inflight:
        return await asyncio.shield(_health_inflight[name])
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _health_inflight[name] = future
    t0 = time.monotonic()
    try:
        try:
            status, detail = await asyncio.wait_for(asyncio.to_thread(check, config, *args), timeout_s)
        except TimeoutError:
            status, detail = "FAIL", f"{name} did not answer within {timeout_s:.0f} s"
        except Exception as e:  # noqa: BLE001 - a check that raises is a failed check
            status, detail = "FAIL", f"{type(e).__name__}: {str(e)[:200]}"
        result = {
            "status": "ok" if status == "OK" else status.lower(),
            "detail": _redact(str(detail), config),
            "latency_ms": round((time.monotonic() - t0) * 1000),
        }
        _health_cache[name] = (time.monotonic(), result)
        future.set_result(result)
        return result
    finally:
        _health_inflight.pop(name, None)
        if not future.done():
            future.cancel()  # waiters of a cancelled check are not left hanging


# One route per dependency, each polled on its own by the UI, so a slow LLM
# (a cold free-tier model can take a minute) never delays or fails the
# TigerGraph and embedding indicators. Unauthenticated — the browser polls.
@app.get("/health/db")
async def health_db(config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    from ogr.verify import check_tigergraph

    return await _timed_check(
        "TigerGraph", HEALTH_DB_TIMEOUT_S, check_tigergraph, config, _get_client(config)
    )


@app.get("/health/llm")
async def health_llm(config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    from ogr.verify import check_llm

    return await _timed_check("LLM", config.health_llm_timeout_s, check_llm, config)


@app.get("/health/embedding")
async def health_embedding(config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    from ogr.verify import check_embedding

    return await _timed_check("Embedding", HEALTH_EMBEDDING_TIMEOUT_S, check_embedding, config)


# ---------------------------------------------------------------- /query ---


@router.post("/query", status_code=202)
async def post_query(body: QueryRequest, config: RunConfig = Depends(get_config)) -> dict[str, str]:
    # Blocked, not warned: a query never searches an index of another model.
    config = await asyncio.to_thread(_query_config, config, body.embedding_model)
    _evict_finished(_queries)
    query_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _queries[query_id] = {"queue": queue, "record": None}
    task = asyncio.create_task(_run_query(query_id, body.query, queue, config))
    _queries[query_id]["task"] = task
    return {"query_id": query_id}


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

    started = time.monotonic()
    await asyncio.gather(_rag(), _graphrag(), _agentic())

    # The stream always ends with "done", even if aggregation or the trial log
    # fails — otherwise the browser waits on a run that is already over.
    try:
        query_record = aggregate_query(query_id=query_id, query_text=query, records=records)
        _queries[query_id]["record"] = query_record
        statuses = {r.status for r in records.values()}
        _trials().append(
            "query",
            "done" if statuses == {"done"} else "error" if statuses == {"error"} else "partial",
            subject=query,
            query_id=query_id,
            duration_ms=round((time.monotonic() - started) * 1000),
            tokens=sum(r.tokens.total for r in records.values()),
            pipelines={
                name: {
                    "status": r.status,
                    "tokens": r.tokens.total,
                    "latency_ms": round(r.latency_ms),
                    "error": r.error_detail,
                }
                for name, r in records.items()
            },
            error="; ".join(f"{n}: {r.error_detail}" for n, r in records.items() if r.error_detail) or None,
            **_model_fields(config),
        )
    except Exception as e:  # noqa: BLE001 - the per-pipeline records are still served
        logger.error("Query %s finished but could not be aggregated: %s", query_id, e)
        if _queries[query_id].get("record") is None:
            _queries[query_id]["record"] = QueryLevelRecord(
                query_id=query_id, query_text=query, pipelines=records
            )
    finally:
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
async def query_stream(query_id: str):
    if query_id not in _queries:
        raise HTTPException(status_code=404, detail="Unknown query_id")
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


DATASET_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def _registry() -> DatasetRegistry:
    return DatasetRegistry(OUT_DIR / "datasets.json")


def _corpus_file(name: str) -> Path:
    if not DATASET_RE.match(name):
        raise HTTPException(
            status_code=400, detail=f"Invalid dataset name {name!r} (letters, digits, _ and -)"
        )
    return CORPUS_DIR / f"{name}.jsonl"


_LIVE_VERTEX_TYPES = {"documents": "Document", "events": "OlympicEvent", "chunks": "Chunk",
                      "games": "Games", "sports": "Sport", "venues": "Venue"}
LIVE_COUNT_TIMEOUT_S = 15.0


def _live_graph_counts(client: TigerGraphClient) -> dict[str, int] | None:
    """Vertex counts read from TigerGraph itself, or None when it cannot be
    reached. Used when this install has no record of the graph (a fresh
    checkout, or a graph built from another machine): the data is there even
    though out/datasets.json is not."""
    client._ensure_connection()
    if client.conn is None:
        return None
    try:
        return {key: int(client.conn.getVertexCount(vtype) or 0) for key, vtype in _LIVE_VERTEX_TYPES.items()}
    except Exception:  # noqa: BLE001 - unreachable or no schema yet: nothing to show
        return None


@router.get("/corpora")
async def get_corpora(config: RunConfig = Depends(get_config)) -> dict[str, Any]:
    """Datasets available to build (JSONL files in data/corpus/) and which of
    them are loaded into the graph. `graph.live` carries TigerGraph's own
    counts when no dataset is recorded here, so existing data still shows."""
    await asyncio.to_thread(_ensure_adopted)
    registry = _registry().summary()
    registry["live"] = None
    if not registry["datasets"]:
        try:
            registry["live"] = await asyncio.wait_for(
                asyncio.to_thread(_live_graph_counts, _get_client(config)), LIVE_COUNT_TIMEOUT_S
            )
        except TimeoutError:
            registry["live"] = None
    corpora = []
    for path in sorted(CORPUS_DIR.glob("*.jsonl")) if CORPUS_DIR.exists() else []:
        # `title` is the name shown for the dataset; `name` stays its id.
        described = await asyncio.to_thread(dataset_meta.describe, path)
        corpora.append({
            "name": path.stem,
            "size_bytes": path.stat().st_size,
            "built": registry["datasets"].get(path.stem),
            **described,
        })
    return {"corpora": corpora, "graph": registry}


class CorpusPatch(BaseModel):
    # An empty title clears the given one: the inferred name shows again.
    title: str | None = None
    description: str | None = None


@router.patch("/corpora/{name}")
async def patch_corpus(name: str, body: CorpusPatch) -> dict[str, Any]:
    """Rename a dataset (its display title); its id and file stay as they are."""
    path = _corpus_file(name)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Unknown dataset {name!r}")
    meta = dataset_meta.read_meta(path)
    if body.title is not None:
        meta["title"] = dataset_meta.clean_title(body.title)
    if body.description is not None:
        meta["description"] = dataset_meta.clean_title(body.description, limit=500)
    dataset_meta.write_meta(path, replace=True, **meta)
    return {"name": name, **await asyncio.to_thread(dataset_meta.describe, path)}


@router.post("/corpora/{name}", status_code=201)
async def upload_corpus(
    name: str,
    request: Request,
    overwrite: bool = False,
    unique: bool = False,
    title: str | None = None,
    source_file: str | None = None,
) -> dict[str, Any]:
    """Add a dataset: the request body is the JSONL itself, one document per
    line with at least `doc_id` and `text` (`title`, `url` optional). `title`
    names the dataset; without it a name is inferred from the documents.
    With `unique`, a taken id gets a suffix (`corpus-2`) instead of a 409 —
    uploads that share a file name then sit side by side."""
    path = _corpus_file(name)
    if path.exists() and unique and not overwrite:
        stem = name[:60]
        suffix = 2
        while (path := _corpus_file(f"{stem}-{suffix}")).exists():
            suffix += 1
        name = path.stem
    if path.exists() and not overwrite:
        raise HTTPException(status_code=409, detail=f"Dataset {name!r} already exists")
    if overwrite and any(
        b.get("dataset") == name and not b["task"].done() for b in list(_builds.values()) if "task" in b
    ):
        raise _conflict("build_running", f"Dataset {name!r} is being built; replace it once the build ends.")
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File larger than {MAX_UPLOAD_BYTES // 2**20} MB")

    # Streamed to a temporary file with a running size check: a large body is
    # never held in memory, and validation runs off the event loop.
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CORPUS_DIR / f".upload-{uuid.uuid4().hex}.part"
    size = 0
    try:
        with tmp.open("wb") as handle:
            async for piece in request.stream():
                size += len(piece)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413, detail=f"File larger than {MAX_UPLOAD_BYTES // 2**20} MB"
                    )
                handle.write(piece)
        documents = await asyncio.to_thread(_validate_corpus_file, tmp)
        # Exclusive unless replacing: two uploads racing for one name cannot
        # silently overwrite each other.
        try:
            await asyncio.to_thread(os.replace if overwrite else os.link, tmp, path)
        except FileExistsError as e:
            raise HTTPException(status_code=409, detail=f"Dataset {name!r} already exists") from e
    finally:
        tmp.unlink(missing_ok=True)
    if overwrite:
        dataset_meta.meta_path(path).unlink(missing_ok=True)
    dataset_meta.write_meta(
        path,
        title=dataset_meta.clean_title(title),
        source_file=dataset_meta.clean_title(source_file),
        uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    described = await asyncio.to_thread(dataset_meta.describe, path)
    return {"name": name, "size_bytes": size, **described, "documents": documents}


def _validate_corpus_file(path: Path) -> int:
    """Documents in an uploaded JSONL file, or a 400 naming the first bad line."""
    documents = 0
    try:
        with path.open(encoding="utf-8") as handle:  # strict: bytes that are not UTF-8 are refused
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as e:
                    raise HTTPException(status_code=400, detail=f"Line {number} is not JSON: {e.msg}") from e
                if not isinstance(record, dict) or not isinstance(record.get("doc_id"), str) \
                        or not isinstance(record.get("text"), str):
                    raise HTTPException(
                        status_code=400, detail=f"Line {number} needs string 'doc_id' and 'text'"
                    )
                documents += 1
    except UnicodeDecodeError as e:
        raise HTTPException(status_code=400, detail=f"The file is not UTF-8 text ({e.reason})") from e
    if not documents:
        raise HTTPException(status_code=400, detail="No documents in the file")
    return documents


class BuildRequest(BaseModel):
    dataset: str = DEFAULT_DATASET
    # The dataset is already loaded: delete its data and load it again.
    rebuild: bool = False
    # Drop and recreate the whole graph (every dataset) — needed once for a
    # graph built before dataset tracking or with another embedding size.
    reset: bool = False


def _conflict(code: str, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": code, "message": message, **extra})


def _graph_has_documents(client: TigerGraphClient) -> bool:
    client._ensure_connection()
    if client.conn is None:
        return False
    try:
        return int(client.conn.getVertexCount("Document") or 0) > 0
    except Exception:  # noqa: BLE001 - no graph yet reads as empty
        return False


@router.post("/build", status_code=202)
async def post_build(
    body: BuildRequest | None = None, config: RunConfig = Depends(get_config)
) -> dict[str, str]:
    body = body or BuildRequest()
    try:
        return await _start_build(body, config)
    except HTTPException as e:
        # A refused build is a trial too: the user sees why it did not run
        # (unknown dataset, already built -> asked to rebuild, reset needed).
        detail = e.detail if isinstance(e.detail, dict) else {"message": str(e.detail)}
        _trials().append(
            "build",
            "needs_confirmation" if detail.get("code") in ("already_built", "reset_required") else "refused",
            subject=body.dataset,
            dataset=body.dataset,
            rebuild=body.rebuild,
            reset=body.reset,
            code=detail.get("code"),
            error=detail.get("message"),
            **_model_fields(config),
        )
        raise


async def _start_build(body: BuildRequest, config: RunConfig) -> dict[str, str]:
    corpus = _corpus_file(body.dataset)
    if not corpus.exists():
        raise HTTPException(status_code=404, detail=f"Unknown dataset {body.dataset!r}")
    if _build_running():
        raise _conflict("build_running", "A build is already running; wait for it to finish.")
    if _embedding_job_running():
        # The job embeds the corpus the build would change under it.
        raise _conflict("embedding_job_running", "A re-embed job is running; build once it finishes.")
    if _batch_running():
        # A reset or rebuild would change the graph under the run's questions.
        raise _conflict("batch_running", "A benchmark run is in progress; build once it finishes.")
    _evict_finished(_builds)
    build_id = str(uuid.uuid4())
    _builds[build_id] = {"task": _Reserved(), "dataset": body.dataset, "events": [], "started": time.time()}
    try:
        return await _checked_build(build_id, body, config)
    except BaseException:
        _builds.pop(build_id, None)
        raise


async def _checked_build(build_id: str, body: BuildRequest, config: RunConfig) -> dict[str, str]:
    # A graph built elsewhere is adopted first, so building its dataset asks
    # to rebuild that dataset instead of resetting the whole graph.
    await asyncio.to_thread(_ensure_adopted)

    registry = _registry()
    store = _embedding_store()
    active = config.embedding_model
    if not body.reset and active not in store.stored() and len(store.stored()) >= MAX_STORED_MODELS:
        # Only after a switch failed mid-eviction: resume it first (the cap).
        raise _conflict(
            "embedding_cap",
            f"{len(store.stored())} models' embeddings are stored and the active one is not among them; "
            "resume the failed re-embed job in Settings before building.",
        )
    if not body.reset:
        if registry.exists and not registry.current_layout():
            raise _conflict(
                "reset_required",
                "The graph was built with one vector on each Chunk; embedding switching keeps each "
                "model's embeddings in its own vertex type. Building needs a full reset, which removes "
                "every loaded dataset.",
            )
        if not registry.exists and await asyncio.to_thread(_graph_has_documents, _get_client(config)):
            raise _conflict(
                "reset_required",
                "The graph already holds data from a build made before dataset tracking (possibly "
                "with 384-dim vectors). Building needs a full reset, which removes that data.",
            )
        existing = registry.get(body.dataset)
        if existing and not body.rebuild:
            built = existing["built_at"][:19].replace("T", " ")
            raise _conflict(
                "already_built",
                f"Dataset {body.dataset!r} was already built on {built} "
                f"UTC ({existing.get('documents', 0)} documents). Rebuild it (delete its data and load "
                "again) or cancel.",
                built_at=existing["built_at"],
            )

    queue: asyncio.Queue = asyncio.Queue()
    _builds[build_id].update(queue=queue)
    task = asyncio.create_task(_run_build(build_id, queue, config, body))
    _builds[build_id]["task"] = task
    return {"build_id": build_id}


async def _run_build(build_id: str, queue: asyncio.Queue, config: RunConfig, request: BuildRequest) -> None:
    """The same stages as `ogr.cli build`, streamed as BuildEvents under the
    stage names the build view renders, for one dataset. Other datasets
    already in the graph are left intact: the schema is installed (dropping
    the graph) only for the first build or an explicit reset. A pipeline
    turns ready only when it can answer: every pipeline queries TigerGraph, so
    nothing is ready until the graph is loaded, Q1-Q5 are installed and the
    vector index reports Ready_for_query (TECHNICAL-SPEC §11). A failed stage
    reports an error rather than a fabricated success (DP-7).
    """
    from ogr.common.embeddings import embedding_backend
    from ogr.graph.schema import install_queries, install_schema
    from ogr.graph.vector_status import wait_until_ready
    from ogr.ingest.chunk_embed import embed_chunks
    from ogr.ingest.embedding_index import CHECKPOINT_BATCH

    events = _builds[build_id].setdefault("events", []) if build_id in _builds else []

    def on_event(event: BuildEvent) -> None:
        # Kept per build so a reloaded page can pick up a running build.
        events.append(event.__dict__)
        queue.put_nowait(("build", event))

    corpus = CORPUS_DIR / f"{request.dataset}.jsonl"
    registry = _registry()
    store = _embedding_store()
    # A build embeds with the active model only; another stored model is left
    # without the new chunks (shown incomplete, completed from Settings).
    model = resolve_model(config.embedding_model)
    progress = BuildProgress(on_event=on_event)
    # Which pipelines each stage serves: RAG answers from chunk vectors only,
    # GraphRAG from the graph only, Agentic GraphRAG from the graph with the
    # vector search as its fallback tool. Every pipeline needs TigerGraph.
    everyone = ["rag", "graphrag", "agentic_graphrag"]
    graph_pipelines = ["graphrag", "agentic_graphrag"]
    vector_pipelines = ["rag", "agentic_graphrag"]
    stage, affected = "parse_infoboxes", graph_pipelines
    ready_ms: dict[str, int] = {}
    started = time.monotonic()
    outcome: dict[str, Any] = {}

    def begin(name: str, pipelines: list[str], items_total: int = 0) -> None:
        nonlocal stage, affected
        stage, affected = name, pipelines
        progress.start(name, pipelines, items_total=items_total)

    try:
        if not corpus.exists():
            raise FileNotFoundError(f"{corpus} not found")

        begin("parse_infoboxes", graph_pipelines)
        docs, _report = await asyncio.to_thread(parse_corpus, corpus)
        progress.finish(stage, affected, items_done=len(docs), note=f"dataset {request.dataset}")

        begin("chunk_documents", vector_pipelines)
        chunks = await asyncio.to_thread(
            chunk_and_embed_corpus, corpus, config.chunk_tokens, config.chunk_overlap, False
        )
        progress.finish(stage, affected, items_done=len(chunks))

        begin("embed_chunks", vector_pipelines, items_total=len(chunks))
        step = CHECKPOINT_BATCH
        for start in range(0, len(chunks), step):
            # strict: vectors that reach an index come from the model, never hash noise.
            await asyncio.to_thread(embed_chunks, chunks[start:start + step], model.key, True)
            progress.progress(stage, affected, min(start + step, len(chunks)), len(chunks))
        backend = await asyncio.to_thread(embedding_backend, model.key)
        progress.finish(
            stage, affected, items_done=len(chunks), note=f"{model.label} via {backend}"
        )

        client = _get_client(config)
        begin("schema_install", everyone)
        # Embedding can take hours on CPU; never reuse a connection that sat
        # idle that long (r: a 5 h build failed here on a connection reset).
        await asyncio.to_thread(client.reconnect)
        if client.conn is None:
            raise ConnectionError("TigerGraph unreachable — set TG_HOST and credentials")
        if request.reset or not registry.exists:
            await asyncio.to_thread(_retry_on_dropped_connection, client, install_schema, client)
            registry.reset(model.key, model.dim)
            store.reset(model.key)
            progress.finish(stage, affected, items_done=1, note="graph created (empty)")
        else:
            loaded = ", ".join(registry.read()["datasets"]) or "none"
            progress.finish(stage, affected, items_done=0, note=f"schema kept; datasets loaded: {loaded}")

        if request.rebuild and registry.get(request.dataset):
            begin("remove_previous", everyone)
            removable = registry.removable_ids(request.dataset)
            # Deleting a Chunk drops its HAS_EMBEDDING edges but not the
            # Embedding_* vertices, so each stored model's are removed too.
            gone = removable.get("Chunk", [])
            for key in store.stored():
                await asyncio.to_thread(client.delete_embeddings, EMBEDDING_MODELS[key], gone)
            store.remove_covered(gone)
            removed = await asyncio.to_thread(_delete_vertices, client, removable)
            registry.forget(request.dataset)
            progress.finish(
                stage, affected, items_done=removed, note=f"removed {request.dataset}'s previous data"
            )

        # One load call writes graph and chunk vertices; its counts are
        # reported to the pipelines each part serves.
        begin("load_vertices", graph_pipelines)
        load = await asyncio.to_thread(
            _retry_on_dropped_connection, client, load_graph, client, docs, chunks, 500, model.key
        )
        entities = load.documents + load.olympic_events + load.games + load.sports + load.venues
        relationships = load.edges - load.chunks  # every chunk adds one HAS_CHUNK edge
        progress.finish(
            stage, affected, items_done=entities, note="Document, OlympicEvent, Games, Sport, Venue"
        )
        begin("load_edges", graph_pipelines)
        progress.finish(
            stage, affected, items_done=relationships,
            note=f"PREV_EDITION {load.prev_edges_resolved} resolved, NEXT_EDITION {load.next_edges_resolved}",
        )
        begin("load_chunks", vector_pipelines, items_total=load.chunks)
        progress.finish(
            stage, affected, items_done=load.chunks,
            note=f"Chunk vertices + {model.vertex_type} ({model.label}, {model.dim}-dim)",
        )
        registry.record(
            request.dataset,
            ids={
                "doc_ids": [d.doc_id for d in docs],
                "event_ids": [d.event_id or d.doc_id for d in docs if d.is_olympic_event],
                "chunk_ids": [c.chunk_id for c in chunks],
            },
            counts={
                "documents": load.documents, "events": load.olympic_events, "chunks": load.chunks,
                "entities": entities, "relationships": relationships, "vectors": load.chunks,
                "embedding_backend": backend, "embedding_model": model.key,
            },
            file_bytes=corpus.stat().st_size,
        )
        # Written now, queryable once the index is ready: if the build fails
        # after this point, "Complete" in Settings only waits for the index
        # instead of re-embedding the whole corpus.
        store.add_covered(model.key, [c.chunk_id for c in chunks], backend, indexing=True)

        begin("install_graph_queries", everyone, items_total=5)
        await asyncio.to_thread(install_queries, client)
        client._vocab_cache.clear()  # the reload may have changed Games/Sport/Venue
        progress.finish(stage, affected, items_done=5)
        # GraphRAG needs no vectors: answerable once the graph and Q1-Q4 are in.
        progress.ready(["graphrag"])
        ready_ms["graphrag"] = round((time.monotonic() - started) * 1000)

        begin("vector_index", vector_pipelines)
        await asyncio.to_thread(wait_until_ready, config, 600.0, conn=client.conn)
        progress.finish(stage, affected, items_done=1, note="Ready_for_query")
        # Complete only once queryable: a model is never 'complete' before its index is.
        store.finish_indexing(model.key)
        if not store.active():
            store.set_active(model.key)
        progress.ready(vector_pipelines)
        ready_ms.update(dict.fromkeys(vector_pipelines, round((time.monotonic() - started) * 1000)))
        registry.update(request.dataset, ready_ms=ready_ms)
        outcome = {"status": "ready", "documents": load.documents, "chunks": load.chunks}
    except Exception as e:  # noqa: BLE001 - reported on the stage that failed
        logger.error("Build %s failed at %s: %s", build_id, stage, e)
        progress.error(stage, affected, str(e))
        outcome = {"status": "error", "failed_stage": stage, "error": str(e)[:500]}

    _trials().append(
        "build",
        outcome.pop("status"),
        subject=request.dataset,
        build_id=build_id,
        dataset=request.dataset,
        rebuild=request.rebuild,
        reset=request.reset,
        duration_ms=round((time.monotonic() - started) * 1000),
        **outcome,
        **_model_fields(config),
    )
    await queue.put(("done", None))


def _is_dropped_connection(error: BaseException) -> bool:
    text = f"{type(error).__name__} {error}"
    return any(s in text for s in ("ConnectionReset", "Connection aborted", "RemoteDisconnected",
                                   "ConnectionError", "BrokenPipe"))


def _retry_on_dropped_connection(client: TigerGraphClient, fn: Any, *args: Any) -> Any:
    """Run a graph step; if the connection was dropped, reconnect and run it
    once more. Schema install and loading are idempotent (drop-and-create,
    upserts), so a second attempt cannot duplicate data."""
    try:
        return fn(*args)
    except Exception as e:  # noqa: BLE001 - only a dropped connection is retried
        if not _is_dropped_connection(e):
            raise
        logger.warning("TigerGraph connection dropped (%s); reconnecting and retrying once", e)
        client.reconnect()
        return fn(*args)


def _delete_vertices(client: TigerGraphClient, ids_by_type: dict[str, list[str]], batch: int = 500) -> int:
    """Delete vertices (and so their edges) by id, in bulk per type."""
    return sum(client.delete_by_ids(vtype, ids) for vtype, ids in ids_by_type.items() if ids)


@router.get("/build/current")
async def get_current_build() -> dict[str, Any]:
    """The latest build of this server process with every event so far, so a
    reloaded page can show a running build and keep following it."""
    latest = max(
        ((bid, b) for bid, b in _builds.items() if "task" in b), key=lambda item: item[1].get("started", 0),
        default=None,
    )
    if latest is None:
        return {"build": None}
    build_id, build = latest
    return {"build": {
        "build_id": build_id,
        "dataset": build.get("dataset"),
        "running": not build["task"].done(),
        "events": list(build.get("events", [])),
    }}


@app.get("/build/{build_id}/stream")
async def build_stream(build_id: str):
    if build_id not in _builds:
        raise HTTPException(status_code=404, detail="Unknown build_id")
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
    # Continue an existing, unfinished run: questions already recorded are
    # skipped (the batch runner resumes by question id).
    resume: bool = False


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
    try:
        return await _start_batch(body, config)
    except HTTPException as e:
        _trials().append(
            "benchmark", "refused", subject=body.dataset, dataset=body.dataset, run_id=body.run_id,
            code=e.detail.get("code") if isinstance(e.detail, dict) else None,
            error=e.detail.get("message", str(e.detail)) if isinstance(e.detail, dict) else str(e.detail),
            **_model_fields(config),
        )
        raise


async def _start_batch(body: BatchRequest, config: RunConfig) -> dict[str, str]:
    """Execute a benchmark over a named question set in `data/questions/`.
    Records append to `out/{run_id}.jsonl`, which makes the run part of the
    history as soon as its first question completes.
    """
    if body.dataset not in _datasets():
        raise HTTPException(status_code=404, detail=f"Unknown dataset {body.dataset!r}")
    started = datetime.now(UTC)
    run_id = body.run_id or started.strftime("%Y%m%dT%H%M%SZ")
    if not is_run_id(run_id):
        raise HTTPException(status_code=400, detail=f"Invalid run id {run_id!r}")
    out_path = OUT_DIR / f"{run_id}.jsonl"
    taken = run_id in _batch_tasks and not _batch_tasks[run_id].done()
    if (out_path.exists() and not body.resume) or taken:
        raise HTTPException(
            status_code=409, detail=f"Run {run_id!r} already exists; pass resume to continue it"
        )
    if body.resume and not out_path.exists():
        raise HTTPException(status_code=404, detail=f"No run {run_id!r} to resume")
    if _build_running() or _embedding_job_running():
        raise _conflict("busy", "A build or re-embed job is running; start the run once it finishes.")
    _batch_tasks[run_id] = _Reserved()  # type: ignore[assignment]
    try:
        return await _launch_batch(body, config, run_id, out_path, started)
    except BaseException:
        _batch_tasks.pop(run_id, None)
        raise


async def _launch_batch(
    body: BatchRequest, config: RunConfig, run_id: str, out_path: Path, started: datetime
) -> dict[str, str]:
    if body.latency_mode:
        config = config.model_copy(update={"latency_mode": body.latency_mode})
    # Same hard block as a query: a run searches only complete embeddings.
    config = await asyncio.to_thread(_query_config, config, None)

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
    started_clock = time.monotonic()

    def _record_benchmark(task: asyncio.Task) -> None:
        error = None if task.cancelled() else task.exception()
        status = "cancelled" if task.cancelled() else "error" if error else "complete"
        _trials().append(
            "benchmark",
            status,
            subject=f"{body.dataset} · {run_id}",
            run_id=run_id,
            dataset=body.dataset,
            questions=None if error else task.result(),
            duration_ms=round((time.monotonic() - started_clock) * 1000),
            error=str(error)[:500] if error else None,
            **_model_fields(config),
        )

    _batch_tasks[run_id].add_done_callback(_record_benchmark)
    return {"run_id": run_id, "status": "running"}


@router.get("/history")
async def get_history(
    kind: Literal["query", "build", "benchmark"] | None = None, limit: int = 500
) -> list[dict]:
    """Every query, build and benchmark attempt, newest first."""
    return await asyncio.to_thread(_trials().read, kind, min(max(limit, 1), 5000))


@router.get("/runs")
async def get_runs() -> list[dict[str, Any]]:
    """Benchmark history: one summary per stored run, newest first. A failed
    run carries its `error` — e.g. the rate-limit stop naming provider/model."""
    runs = await asyncio.to_thread(list_runs, OUT_DIR, _run_statuses())
    for run in runs:
        task = _batch_tasks.get(run["run_id"])
        if task is not None and task.done() and not task.cancelled() and task.exception():
            run["error"] = str(task.exception())
    return runs


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
    if not is_run_id(run_id) or not path.exists():
        raise HTTPException(status_code=404, detail=f"No run {run_id!r}")
    _run_config, records = read_run(path)
    return [view_record(r) for r in records]


app.include_router(router)
