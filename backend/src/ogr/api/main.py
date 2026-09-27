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
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from ogr.api.security import StreamTokenStore, get_config, require_api_key
from ogr.common.config import RunConfig, get_default_config
from ogr.common.contracts import PipelineRecord, QueryLevelRecord
from ogr.common.trials import TrialLog
from ogr.eval.aggregator import aggregate_query
from ogr.eval.batch_runner import default_pipelines, effective_pool_size, run_batch, run_config_header
from ogr.eval.dispatcher import error_record
from ogr.eval.history import RUN_ID_RE, import_run, list_runs, read_run, summarize_run, view_record
from ogr.graph.client import TigerGraphClient
from ogr.ingest import dataset_meta
from ogr.ingest.chunk_embed import chunk_and_embed_corpus
from ogr.ingest.infobox import parse_corpus
from ogr.ingest.load import load_graph
from ogr.ingest.progress import BuildEvent, BuildProgress
from ogr.ingest.registry import DatasetRegistry
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
    return base.model_copy(update=_runtime_overrides) if _runtime_overrides else base


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


class SettingsPatch(BaseModel):
    llm_provider: Literal["gemini", "nvidia_nim", "groq"] | None = None
    llm_model: str | None = None
    embedding_model: str | None = None


# Embedding dim is fixed per supported model; unknown models keep current dim.
_EMBEDDING_DIMS: dict[str, int] = {
    "@cf/baai/bge-m3": 1024,
}


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


def _settings_body(cfg: RunConfig) -> dict[str, Any]:
    from urllib.parse import urlparse

    return {
        "llm_provider": cfg.llm_provider,
        # The preset id serving the model, or None for a provider outside the
        # presets (then `llm_base_host` says where it runs).
        "llm_provider_preset": _provider_preset(cfg),
        "llm_base_host": urlparse(cfg.llm_base_url or "").netloc or None,
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
def patch_settings(body: SettingsPatch) -> dict[str, Any]:
    """Update runtime model/embedding without a server restart. The selected
    LLM applies to all three pipelines: each run snapshots config once."""
    global _tg_client
    if body.llm_provider is not None:
        from ogr.common.llm import PROVIDER_PRESETS

        if not body.llm_model:
            raise HTTPException(422, "llm_model is required when changing llm_provider")
        preset = PROVIDER_PRESETS[body.llm_provider]
        key = getattr(get_default_config(), preset["key_field"])
        if not key:
            raise HTTPException(400, f"{preset['key_field'].upper()} is not set on the server")
        _runtime_overrides.update(
            llm_provider=body.llm_provider, llm_base_url=preset["base_url"] or None, llm_api_key=key
        )
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
    return _settings_body(_get_config_with_overrides())


async def _timed_check(name: str, timeout_s: float, check, *args) -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        status, detail = await asyncio.wait_for(asyncio.to_thread(check, *args), timeout_s)
    except TimeoutError:
        status, detail = "FAIL", f"{name} did not answer within {timeout_s:.0f} s"
    return {
        "status": "ok" if status == "OK" else status.lower(),
        "detail": detail,
        "latency_ms": round((time.monotonic() - t0) * 1000),
    }


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

    started = time.monotonic()
    await asyncio.gather(_rag(), _graphrag(), _agentic())

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


@router.get("/corpora")
async def get_corpora() -> dict[str, Any]:
    """Datasets available to build (JSONL files in data/corpus/) and which of
    them are loaded into the graph."""
    registry = _registry().summary()
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
        meta["description"] = dataset_meta.clean_title(body.description)
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
    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File larger than {MAX_UPLOAD_BYTES // 2**20} MB")
    documents = 0
    for number, line in enumerate(body.decode("utf-8", errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Line {number} is not JSON: {e.msg}") from e
        if not isinstance(record, dict) or not isinstance(record.get("doc_id"), str) \
                or not isinstance(record.get("text"), str):
            raise HTTPException(status_code=400, detail=f"Line {number} needs string 'doc_id' and 'text'")
        documents += 1
    if not documents:
        raise HTTPException(status_code=400, detail="No documents in the file")
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    if overwrite:
        dataset_meta.meta_path(path).unlink(missing_ok=True)
    dataset_meta.write_meta(
        path,
        title=dataset_meta.clean_title(title),
        source_file=dataset_meta.clean_title(source_file),
        uploaded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )
    described = await asyncio.to_thread(dataset_meta.describe, path)
    return {"name": name, "size_bytes": len(body), **described, "documents": documents}


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
    if any(not b["task"].done() for b in _builds.values() if "task" in b):
        raise _conflict("build_running", "A build is already running; wait for it to finish.")

    registry = _registry()
    if not body.reset:
        schema = registry.read().get("schema")
        if schema and schema.get("embedding_dim") != config.embedding_dim:
            raise _conflict(
                "reset_required",
                f"The graph holds {schema.get('embedding_dim')}-dim vectors but the embedding model "
                f"produces {config.embedding_dim}-dim ones. Building needs a full reset, which removes "
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

    _evict_finished(_builds)
    build_id = str(uuid.uuid4())
    token = _stream_tokens.issue(build_id)
    queue: asyncio.Queue = asyncio.Queue()
    _builds[build_id] = {"queue": queue, "dataset": body.dataset, "events": [], "started": time.time()}
    task = asyncio.create_task(_run_build(build_id, queue, config, body))
    _builds[build_id]["task"] = task
    return {"build_id": build_id, "stream_token": token}


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

    events = _builds[build_id].setdefault("events", []) if build_id in _builds else []

    def on_event(event: BuildEvent) -> None:
        # Kept per build so a reloaded page can pick up a running build.
        events.append(event.__dict__)
        queue.put_nowait(("build", event))

    corpus = CORPUS_DIR / f"{request.dataset}.jsonl"
    registry = _registry()
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
        step = 500
        for start in range(0, len(chunks), step):
            await asyncio.to_thread(embed_chunks, chunks[start:start + step])
            progress.progress(stage, affected, min(start + step, len(chunks)), len(chunks))
        backend = await asyncio.to_thread(embedding_backend)
        progress.finish(
            stage, affected, items_done=len(chunks), note=f"{config.embedding_model} via {backend}"
        )

        client = _get_client(config)
        begin("schema_install", everyone)
        await asyncio.to_thread(client._ensure_connection)
        if client.conn is None:
            raise ConnectionError("TigerGraph unreachable — set TG_HOST and credentials")
        if request.reset or not registry.exists:
            await asyncio.to_thread(install_schema, client)
            registry.reset(config.embedding_model, config.embedding_dim)
            progress.finish(stage, affected, items_done=1, note="graph created (empty)")
        else:
            loaded = ", ".join(registry.read()["datasets"]) or "none"
            progress.finish(stage, affected, items_done=0, note=f"schema kept; datasets loaded: {loaded}")

        if request.rebuild and registry.get(request.dataset):
            begin("remove_previous", everyone)
            removable = registry.removable_ids(request.dataset)
            removed = await asyncio.to_thread(_delete_vertices, client, removable)
            registry.forget(request.dataset)
            progress.finish(
                stage, affected, items_done=removed, note=f"removed {request.dataset}'s previous data"
            )

        # One load call writes graph and chunk vertices; its counts are
        # reported to the pipelines each part serves.
        begin("load_vertices", graph_pipelines)
        load = await asyncio.to_thread(load_graph, client, docs, chunks)
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
        progress.finish(stage, affected, items_done=load.chunks, note="Chunk vertices with bge-m3 vectors")
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
                "embedding_backend": backend,
            },
            file_bytes=corpus.stat().st_size,
        )

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


def _delete_vertices(client: TigerGraphClient, ids_by_type: dict[str, list[str]], batch: int = 500) -> int:
    """Delete vertices (and so their edges) by id, in batches."""
    removed = 0
    for vtype, ids in ids_by_type.items():
        for start in range(0, len(ids), batch):
            removed += int(client.conn.delVerticesById(vtype, ids[start:start + batch]) or 0)
    return removed


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
    try:
        return await _start_batch(body, config)
    except HTTPException as e:
        _trials().append(
            "benchmark", "refused", subject=body.dataset, dataset=body.dataset, run_id=body.run_id,
            error=str(e.detail), **_model_fields(config),
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
    if not RUN_ID_RE.match(run_id) or not path.exists():
        raise HTTPException(status_code=404, detail=f"No run {run_id!r}")
    _run_config, records = read_run(path)
    return [view_record(r) for r in records]


app.include_router(router)
