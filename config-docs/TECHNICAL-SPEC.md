# TECHNICAL-SPEC.md
Agentic GraphRAG Hackathon — Three-Pipeline Comparison System

Status: **v0.4 — synchronised with the code, 2026-09-27.** Supersedes v0.3. Fragment-style; every statement is checked against `backend/src/ogr`, `config/`, `env.example`, `frontend/.env.example` and the `Makefile`. Section numbers §1–§14 are stable (code cites them); new material is added as subsections.

Related documents: `ARCHITECTURE-SPEC.md` (components, routing rule; rationale in its **Decision log**, CI/runtime checks in **Engineering guards**), `EMBEDDING-SWITCHING.md` (per-model embedding storage and switching), `UI-SPEC.md` (screens), `APPLICATION-SPEC.md` (requirements), `README.md` / `DEPLOY.md` (running and deploying). Where this document and the code disagree, the code is the truth and this document is the defect.

---

## 1. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Graph + vector store | TigerGraph Savanna (Community Edition also works) | Per-model HNSW indices (COSINE) on `Embedding_*` vertex types (§2) |
| Embedding model | One of five selectable models (`common/embedding_models.py`): `qwen3-embedding-0.6b` (1024), `embeddinggemma-300m` (768), `gte-large-en-v1.5` (1024), `mxbai-embed-large-v1` (1024), `bge-large-en-v1.5` (1024, **default**). Served by Cloudflare Workers AI where it hosts the model (only `bge-large-en-v1.5`, `@cf/baai/bge-large-en-v1.5`, CLS pooling) and credentials are set, else local `sentence-transformers` | At most 2 models stored at once; switched at runtime from Settings. A query is searched only against its own model's index, chosen by model identity, never by dimension (`EMBEDDING-SWITCHING.md`) |
| Reranker | Cloudflare `@cf/baai/bge-reranker-base` cross-encoder (`common/rerank.py`), P3 fallback prose only | P1 stays unfiltered (AD-9). No credentials or an error → input order kept |
| LLM | Pluggable — `LLM_PROVIDER`: `anthropic`/`claude` → `ChatAnthropic`; `google`/`gemini`/`google_genai` → `ChatGoogleGenerativeAI`; anything else → `ChatOpenAI` at `LLM_BASE_URL`. One boundary: `common/llm.py`, one cached client per model configuration shared by P1/P2/P3, one retry policy, one rate limiter, LangChain `usage_metadata` accounting. Runtime presets (§14.4) | No LLM in the scoring loop. Tool-calling support is probed (`auto`) or forced (§14.1) |
| Backend | Python 3.11 · FastAPI · `sse-starlette` · LangGraph/LangChain · pyTigerGraph ≥ 2.0 | The sync pipelines run in worker threads (`asyncio.to_thread`) and share one `TigerGraphClient`; pyTigerGraph ≥ 2.0 keeps one HTTP session per thread |
| Frontend | React + Vite, native `EventSource` | Per-column async rendering + streaming trace (`UI-SPEC.md`) |
| Reproduce target | `make reproduce` = `install` → `check` → `verify` → `build` → `benchmark` → `timing` → `holdout` (§12) | Needs a filled-in `.env` |

## 2. Graph Schema

Source: `backend/src/ogr/graph/schema.gsql` (idempotent: drops the graph with `CASCADE`, then its edge and vertex types, and recreates them; re-running it requires re-installing Q1–Q5). Kept in step with `common/embedding_models.py` by `test_embedding_schema`.

### 2.1 Vertices

All primary ids are `STRING` with `PRIMARY_ID_AS_ATTRIBUTE="true"`.

| Vertex | Attributes | Vector |
|---|---|---|
| Document | `doc_id` (= wikidata QID), `title`, `url`, `infobox_type` (derived from the `[Infobox <type>]` header), `approx_tokens` INT, `wikipedia_pageid` | — |
| OlympicEvent | `event_id`, `event_name`, `competitors` INT, `competitors_text`, `nations` INT, `nations_text`, `date_text`, `date_month` / `date_day_start` / `date_day_end` / `date_year` INT, `gold` LIST\<STRING\>, `silver` LIST\<STRING\>, `bronze` SET\<STRING\>, `gold_noc`, `win_value`, `win_label`, `parse_confidence` FLOAT | — |
| Games | `games_id` (e.g. `2012-Summer`), `year` INT, `season` | — |
| Sport | `sport_name` | — |
| Venue | `venue_name` | — |
| Chunk | `chunk_id`, `doc_id`, `text`, `seq` INT, `token_count` INT | **none** — a chunk is stored once |
| `Embedding_Qwen` | primary id `chunk_id` | `emb` 1024, COSINE |
| `Embedding_EmbeddingGemma` | primary id `chunk_id` | `emb` 768, COSINE |
| `Embedding_GteLarge` | primary id `chunk_id` | `emb` 1024, COSINE |
| `Embedding_Mxbai` | primary id `chunk_id` | `emb` 1024, COSINE |
| `Embedding_BGELarge` | primary id `chunk_id` | `emb` 1024, COSINE |

The vector attributes are added by the global schema-change job `add_vectors` (GSQL requires `ALTER VERTEX … ADD VECTOR ATTRIBUTE` inside a job). All five embedding types always exist so Q5 always compiles; a model that is not stored has no vertices. There are no Run/Step vertices (trace write-back is cut).

### 2.2 Edges

All directed, endpoints pinned.

| Edge | From → To | Note |
|---|---|---|
| `DESCRIBES` | Document → OlympicEvent | reverse `reverse_DESCRIBES` (Q1/Q3/Q4 resolve an event's `doc_id` through it) |
| `AT_GAMES` | OlympicEvent → Games | |
| `IN_SPORT` | OlympicEvent → Sport | sport derived from the title |
| `HELD_AT` | OlympicEvent → Venue | attr `date_text`; reverse `reverse_HELD_AT` |
| `PREV_EDITION` / `NEXT_EDITION` | OlympicEvent → OlympicEvent | resolved from infobox `prev`/`next` |
| `HAS_CHUNK` | Document → Chunk | |
| `HAS_EMBEDDING` | Chunk → each of the five `Embedding_*` types (multi-pair edge) | reverse `reverse_HAS_EMBEDDING`. Deleting an `Embedding_*` vertex removes only its own edge; the Chunk and other models' embeddings stay |

### 2.3 Schema decisions that matter

| Decision | Why |
|---|---|
| `competitors`/`nations` typed INT | `competitors > 37` is a native predicate |
| `doc_id` = wikidata QID | Retrieval scoring against `gold_doc_ids` is a set comparison |
| `parse_confidence` on OlympicEvent | Partial parses still load; Q2 reports rows below 0.9 as `excluded_count` instead of dropping them silently |
| `*_text` kept beside the INT (`competitors_text`, `nations_text`) | Some values are non-integer (`23 teams`, `32 (16 pairs)`): leading integer + `parse_confidence < 1.0` |
| Sport from the title prefix | No infobox carries a `sport` field; `<Sport> at the <Games>` parses the Olympic documents |
| Date parsed into typed INTs at ingest | Two date fields (`date`, `dates`) in heterogeneous formats; one normalizer (`common/dates.py`) |
| `bronze` is a SET | Third-place ties (`bronze2`) |
| Person/NOC vertices, `WON_MEDAL` | Cut — medalists are attributes on the event |
| One Chunk + one `Embedding_*` vertex per model | Models are stored, switched and deleted independently (`EMBEDDING-SWITCHING.md` §2) |

## 3. GSQL Query Library (exactly five)

Source: `backend/src/ogr/graph/queries/*.gsql`, installed by `graph/schema.install_queries` (verified with `getInstalledQueries`). All `SYNTAX V2`.

| # | Installed query and parameters (defaults) | Idiom | Serves |
|---|---|---|---|
| Q1 | `q1_lookup(STRING title = "", STRING event_id = "", STRING target_field = "")` | match on `event_id`, else `event_name == title`; prints `EventRow` tuples (medal lists flattened to `"; "`-joined strings, `doc_id` and page `title` via `reverse_DESCRIBES`). No event match with a title → falls back to Document vertices with that title (different row shape, flattened by `client._flatten_vertex`). `target_field` is accepted but unused — the caller picks the field | LOOKUP |
| Q2 | `q2_count_where(STRING anchor_sport = "", STRING anchor_games = "", STRING anchor_venue = "", STRING constraints_json = "[]", STRING field = "competitors")` | anchor filters, then up to **two** constraints from the JSON (third+ ignored) on `competitors` / `nations` / `date_year` with `> < >= <= =`; `SumAccum<INT>`. Prints `count_value`, `excluded_count` (`parse_confidence < 0.9`), then a second block `members` (each counted event's `event_id`, `event_name`, `doc_id`, `title`); the aggregation agent keeps the count row first and at most 30 members | COUNT |
| Q3 | `q3_argmax(STRING anchor_sport = "", STRING anchor_games = "", STRING anchor_venue = "", STRING field = "competitors")` | `HeapAccum<Ranked>(3, value DESC)`; rankable `nations`, anything else ranks `competitors`. Rows: `event_id`, `event_name`, `doc_id`, `title`, `value` | ARGMAX |
| Q4 | `q4_traverse(STRING anchor = "", STRING edge_type = "PREV_EDITION", INT hops = 1)` | `anchor` = event id or name. `PREV_EDITION`/`NEXT_EDITION`: `hops` steps (capped at 10). `HELD_AT`: event → its venues, or venue name → its events via `reverse_HELD_AT`. Event rows: `event_id`, `event_name`, `doc_id`, `title` | TRAVERSE, multi_hop |
| Q5 | `q5_hybrid_search(LIST<FLOAT> query_vector, INT k = 10, STRING emb_type = "Embedding_BGELarge", SET<STRING> candidate_set)` | one branch per `Embedding_*` type: `vectorSearch({T.emb}, q, k, {candidate_set?, distance_map: @@distances})`, then `reverse_HAS_EMBEDDING` to the Chunk. Prints `top_chunks` and `distances`. Unknown `emb_type` → empty | P1, P3 similarity fallback |

Every event row carries its Document's `title`: gold answers are page titles (`Athletics at the 2008 Summer Olympics – Men's marathon`), and infobox `event_name`s can be short or unusable (`Fleet/Match` for Soling), so the model needs the title to answer with it.

Q5 is called only through `TigerGraphClient.hybrid_search`, which derives `emb_type` from the model key (`model.vertex_type`) and refuses a query vector whose length is not that model's dimension (`ValueError`). Scores are `1 - distance` (COSINE), sorted client-side.

**Interpreted (not installed) bulk queries** in `graph/client.py`, run as `INTERPRET QUERY (SET<STRING> ids)` in batches of 200 (`BULK_BATCH`), because pyTigerGraph's per-id REST calls take ~0.4 s each on Savanna:

- `get_chunk_texts(chunk_ids)` — `to_vertex_set(ids, "Chunk")`, returns `{chunk_id: text}`; what a re-embed job embeds. Falls back to per-id `getVerticesById`.
- `delete_by_ids(vertex_type, ids)` — `DELETE v FROM Start:v`; vertex type checked against an identifier regex. Falls back to `delVerticesById`. Used by rebuild (`remove_previous`) and embedding eviction (`delete_embeddings`, which additionally refuses any type outside the embedding catalog).

Other client reads: `_expand_has_chunk` (per-document `getEdges(..., "HAS_CHUNK")` + `getVerticesById`), `get_vocabulary` (Games/Sport/Venue ids, cached per client; empty results not cached).

Vector-index build is asynchronous: `graph/vector_status.wait_until_ready` polls `getVectorIndexStatus()` (REST `/restpp/vector/status`; ready when `NeedRebuildServers` is empty, or `Ready_for_query` on older builds) and raises `VectorNotReadyError` on timeout (600 s in build and re-embed jobs).

## 4. API Surface

Source: `backend/src/ogr/api/main.py`, `api/security.py`. Single-process, in-memory state; finished query/build entries beyond the most recent 100 are dropped.

### 4.0 Route table

**Unauthenticated** (registered on `app`):

| Route | Purpose |
|---|---|
| `GET /health` | `{"status": "ok"}` — process liveness only |
| `GET /health/db` · `/health/llm` · `/health/embedding` | One dependency each (§4.7) |
| `GET /settings` | Effective `llm_provider`, `llm_provider_preset`, `llm_base_host` (host[:port] only), `llm_model`, `embedding_model`, `embedding_dim` |
| `GET /query/{query_id}/stream?token=` | SSE (§5); single-use stream token instead of the key |
| `GET /build/{build_id}/stream?token=` | SSE of `BuildEvent`s |

**Require `X-API-Key`** (registered on `router`, `APIRouter(dependencies=[Depends(require_api_key)])`):

| Route | Body / params | Result |
|---|---|---|
| `GET /settings/providers` | — | `[{id, label, configured}]` (`configured` = its key is set) |
| `GET /settings/models?provider=gemini\|nvidia_nim\|groq` | — | `{provider, models, note}`; 502 if the catalog cannot be listed |
| `PATCH /settings` | `SettingsPatch {llm_provider?, llm_model?, embedding_model?}` | new settings body. 422 provider without model; 400 key not set; 409 `embedding_switch_required` for a model without complete embeddings |
| `GET /embeddings` | — | every model's state, the 2-model cap, the job, `switch_disabled_reason`, `layout_current` |
| `GET /embeddings/plan?model=` | — | what a switch would do now |
| `POST /embeddings/switch` (202) | `EmbeddingSwitch {model, mode?: replace\|parallel, evict?}` | instant switch or a started job |
| `POST /embeddings/resume` (202) | — | resume a failed job from its checkpoint |
| `POST /embeddings/{model}/complete` (202) | — | embed the chunks a stored model lacks |
| `POST /query` (202) | `QueryRequest {query, embedding_model?}` | `{query_id, stream_token}` |
| `GET /query/{query_id}/result` | — | `QueryLevelRecord` (§6.1); 404 unknown, 409 still running |
| `GET /corpora` | — | `{corpora: [{name, size_bytes, built, title, …}], graph: registry summary}` |
| `PATCH /corpora/{name}` | `CorpusPatch {title?, description?}` | renames the display title (empty clears it) |
| `POST /corpora/{name}` (201) | body = raw JSONL; query `overwrite`, `unique`, `title`, `source_file` | `{name, size_bytes, documents, …}` |
| `POST /build` (202) | `BuildRequest {dataset = "corpus", rebuild = false, reset = false}` | `{build_id, stream_token}` |
| `GET /build/current` | — | latest build of this process with all events so far (page reload) |
| `GET /datasets` | — | question files in `data/questions/` (stems) |
| `POST /batch` (202) | `BatchRequest {dataset, run_id?, latency_mode?: throughput\|timing, resume = false}` | `{run_id, status: "running"}` |
| `GET /runs` | — | one summary per stored run, newest first (§9.2), status `running\|complete\|failed`, `error` on failure |
| `POST /runs/import` (201) | `{run_id?, run_config?, records}` or a bare record list | run summary; 409 id taken, 400 malformed |
| `GET /batch/{run_id}/records` | — | scored view records (§9.2); 404 unknown |
| `GET /history?kind=query\|build\|benchmark&limit=500` | — | trial log, newest first (§4.8), limit clamped to 1–5000 |

### 4.1 `POST /query`

`QueryRequest {query, embedding_model}`. `embedding_model` (catalog key/alias) is optional — default the active model; the UI sends it after the user picks a complete model in the mismatch dialog. Before anything runs, `_query_config` checks the chosen model has **complete** embeddings for the loaded corpus; otherwise `409 embedding_mismatch` with `selected` (its status) and `available` (complete models). No fallback to another model. All three pipelines then run concurrently (§11); results stream (§5) and are readable at §4.2.

### 4.2 `GET /query/{query_id}/result`

The `QueryLevelRecord` (§6.1); `409` while running. If aggregation fails the per-pipeline records are still served without a verdict.

### 4.3 `POST /batch`

`BatchRequest {dataset, run_id, latency_mode, resume}`: `dataset` names `data/questions/{dataset}.jsonl`; `run_id` defaults to the UTC timestamp `%Y%m%dT%H%M%SZ` and must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`, not `history|chunks|datasets|embeddings` (400 otherwise); `latency_mode` defaults to `RUN_LATENCY_MODE`; `resume` continues an existing file.

Refusals: 404 unknown dataset / no run to resume; 409 run exists without `resume` (or is running); `409 busy` while a build or re-embed job runs; `409 embedding_mismatch` if the active model is incomplete. Records append to `out/{run_id}.jsonl`.

Question rows (`Question`): `{qid, question, qtype, answer: [str], gold_doc_ids: [str]}` — both `eval_public.jsonl` and `eval_hidden.jsonl` use these names; `answer` is a list of gold variants (empty for the hidden set).

Run header (`batch_runner.run_config_header` + API/CLI additions), first line of the file as `{"run_config": {...}}`:
```json
{ "llm_provider": "string", "llm_model": "string", "llm_base_url": "string|null", "temperature": 0.0,
  "embedding_model": "bge-large-en-v1.5", "embedding_backend": "cloudflare|sentence-transformers|hash_fallback",
  "k": 10, "chunk_tokens": 300, "chunk_overlap": 50, "max_steps": 6, "max_tokens_per_query": 20000,
  "max_total_tokens": 5000000, "pool_size": 2, "latency_mode": "throughput|timing", "seed": null,
  "requests_per_minute": 30.0, "dataset": "eval_public", "started_at": "ISO-8601" }
```
`embedding_backend` names the tier that would serve the model. Query embedding is strict, so with `hash_fallback` the vector paths fail with an error record rather than returning non-semantic results.

**Failure semantics** (`eval/batch_runner.run_batch`): each question is isolated. A pipeline exception becomes an error record (§11); a failure after dispatch (record construction, the store's secret check) leaves the question unwritten and the run ends with `BatchIncompleteError` naming it (`GET /runs` → `failed`, CLI exit 1). The run-level ceiling `max_total_tokens` (0 = off) is counted over the whole file, superseded records included, so it holds across resumes; once reached no question starts, in-flight ones finish (overshoot ≤ `pool_size` questions). An `LLMRateLimitError` stops the run (no further question starts; no provider fallback) and its message names provider/model. Resume semantics: §9.3.

### 4.4 `GET /batch/{run_id}/records`

Scored view records (§9.2) for the dashboard and eval table. Benchmark history: `GET /datasets`, `GET /runs`, `POST /runs/import` (§4.0).

### 4.5 Authentication

`require_api_key` (`api/security.py`) compares `X-API-Key` to `OGR_API_KEY` with `secrets.compare_digest`: missing/wrong → **401**; `OGR_API_KEY` unset → **503** `OGR_API_KEY is not configured` (the API refuses rather than running open). Enforced as a router-level dependency, so a new route on `router` is protected by default.

Browser `EventSource` cannot send headers, so the two SSE routes take `?token=`: issued with the id by `POST /query` / `POST /build`, scoped to that id, single-use, TTL `OGR_STREAM_TOKEN_TTL_S` (default 300 s). Expired tokens are purged on each issue. Invalid/expired/used → 401. The long-lived key never enters a URL.

CORS: `OGR_CORS_ORIGINS` (default `http://localhost:5173,http://127.0.0.1:5173`), `allow_credentials=False`.

### 4.6 `POST /build` · `GET /build/{build_id}/stream`

`BuildRequest {dataset, rebuild, reset}` builds one dataset `data/corpus/{dataset}.jsonl` (name `^[A-Za-z0-9_-]{1,64}$`) into the shared graph; other loaded datasets are kept.

Refusals (409 with `detail = {code, message, …}` unless noted): 404 unknown dataset; `build_running`; `embedding_job_running`; `batch_running`; `embedding_cap` (the active model is not stored and the cap is full — only after a failed eviction; resume the job first); `reset_required` (the registry predates the per-model layout, or the graph holds documents but no registry exists — a full reset removes every dataset); `already_built` (with `built_at`; resend with `rebuild`). `already_built`/`reset_required` are logged as `needs_confirmation` trials, other refusals as `refused`.

Stages streamed as `BuildEvent {stage, pipeline_affected[], status: running|done|error|ready, items_done, items_total, elapsed_ms (since build start), tokens (always 0), note}`:

| Stage | `pipeline_affected` |
|---|---|
| `parse_infoboxes` | graphrag, agentic_graphrag |
| `chunk_documents`, `embed_chunks` (strict, active model only, progress per 500) | rag, agentic_graphrag |
| `schema_install` — installs the schema (drops the graph) only on first build or `reset`; otherwise reports the datasets kept | all |
| `remove_previous` (only with `rebuild` of a loaded dataset) — deletes its ids, plus each stored model's embeddings of its chunks | all |
| `load_vertices`, `load_edges` | graphrag, agentic_graphrag |
| `load_chunks` (Chunk + active model's `Embedding_*`) | rag, agentic_graphrag |
| `install_graph_queries` → **`ready` graphrag** | all |
| `vector_index` (`wait_until_ready`, 600 s) → **`ready` rag, agentic_graphrag** | rag, agentic_graphrag |

Readiness is per pipeline and only when it can answer. A failed stage emits `status: error` on that stage. No LLM runs in this path. Per-pipeline time-to-ready and counts are stored in the registry (§4.8).

### 4.7 Health checks

`/health/db` (`verify.check_tigergraph`: REST++ `echo` through the shared client, 20 s), `/health/llm` (`check_llm`: one completion capped at 32 tokens, `max_retries=0`, `HEALTH_LLM_TIMEOUT_S`, default 120 s), `/health/embedding` (`check_embedding`, 30 s: `ok` = Cloudflare answered; `skip` = local model loaded/cached, degraded but semantic; `fail` = no working tier). Response `{status: ok|fail|skip, detail, latency_ms}`. Each result is **cached 30 s** and concurrent callers share one in-flight check, so polling cannot spend LLM quota. `detail` is redacted: `TG_HOST` and `LLM_BASE_URL` replaced by `<host>`, URL userinfo by `***@`.

### 4.8 Datasets, uploads and the trial log

- **Uploads** `POST /corpora/{name}`: body streamed to a temp file, max **200 MB** (413 from `Content-Length` or while streaming); must be UTF-8 JSONL with string `doc_id` and `text` per line (400 naming the first bad line; 400 if empty). Existing name → 409 unless `overwrite=true` (409 `build_running` if that dataset is being built) or `unique=true` (suffix `-2`, `-3`, …). `title`/`source_file` are stored in a sidecar meta file (`ingest/dataset_meta.py`).
- **Registry** `out/datasets.json` (`ingest/registry.py`): `schema {embedding_model, embedding_dim, layout: "per_model_embeddings"}` and per dataset its vertex ids (Document, OlympicEvent, Chunk), counts, file size, embedding backend/model and `ready_ms`. A rebuild removes only ids no other dataset also wrote.
- **Embedding store** `out/embeddings.json` (`ingest/embedding_index.py`): active model, per-model covered chunk ids, job state (`EMBEDDING-SWITCHING.md` §3, §8).
- **Trial log** `out/history.jsonl` (`common/trials.py`): one line `{id, at, kind, status, …}` per query (`done|partial|error`), build (`ready|error|refused|needs_confirmation`), benchmark (`complete|error|cancelled|refused`) and embedding job, with dataset, provider/model and duration; never keys. Served by `GET /history`.

### 4.9 Conflict codes

`409` bodies are `{code, message, …}`: `embedding_mismatch`, `embedding_switch_required`, `build_running`, `embedding_job_running`, `batch_running`, `busy`, `reset_required`, `already_built`, `embedding_cap`, and from the embedding store (`SwitchRefused`): `mode_required` (model incomplete and no `mode`), `eviction_required` (cap reached and no `evict`), `nothing_to_resume`, `not_stored`, `already_complete`, plus others listed in `EMBEDDING-SWITCHING.md` §9. Unknown embedding model → **422**; upload too large → **413**.

### 4.10 Embedding switching (summary)

Each model's embeddings live in its own `Embedding_*` type and index; at most 2 models are stored. A model with complete embeddings switches instantly (`PATCH /settings` or `POST /embeddings/switch`). Otherwise the request must choose `replace` (delete the outgoing model's embeddings, re-embed) or `parallel` (keep the old one queryable), and at the cap name the model to `evict`. Jobs checkpoint every 500 chunks, can be resumed, and are refused while a build, job or benchmark runs; a job cut off by a restart is marked failed. Full rules: `EMBEDDING-SWITCHING.md`.

## 5. Streaming Protocol (Agentic Trace)

SSE via `sse-starlette`. `POST` returns `202` with a stream token; the stream is `GET …/stream?token=…` (browser `EventSource` is GET-only).

Query stream events: `trace` (one `TraceStep`, §6.3, as P3 produces it), `pipeline` (one `PipelineRecord` the moment that pipeline finishes), and a final `done` (`{}`) — always sent, even if aggregation fails. Build stream: `build` (`BuildEvent`) then `done`. No cancel/interrupt (would need WebSocket).

## 6. Data Model

Source: `common/contracts.py` (Pydantic).

### 6.1 Query-level record (`QueryLevelRecord`)

```json
{
  "query_id": "string",
  "query_text": "string",
  "qtype": "lookup|multi_hop|temporal|aggregation|superlative|null",
  "timestamp": "ISO-8601",
  "pipelines": { "rag": "PipelineRecord", "graphrag": "PipelineRecord", "agentic_graphrag": "PipelineRecord" },
  "verdict": {
    "token_multiplier_vs_rag": "number|null",
    "token_multiplier_vs_graphrag": "number|null",
    "accuracy_delta_vs_rag": "number|\"n/a\"",
    "accuracy_delta_vs_graphrag": "number|\"n/a\"",
    "summary_line": "string"
  }
}
```
Verdict (`eval/aggregator.py`, one implementation for API and batch): multipliers = agentic tokens / baseline tokens rounded to 2 dp, **null** when the baseline spent 0 tokens; accuracy deltas = EM difference rounded to 2 dp, `"n/a"` without ground truth (interactive queries). `qtype` is null for interactive queries.

### 6.2 PipelineRecord

```json
{
  "pipeline": "rag|graphrag|agentic_graphrag",
  "answer": "string (short span — scored)",
  "explanation": "string (prose with citations — displayed, never scored)",
  "citations": [ { "source_id": "doc_id (scored)", "chunk_id": "string|null", "ref_type": "chunk|entity|relationship", "snippet": "cited evidence text, ≤600 chars|null" } ],
  "chunks_returned": 0,
  "citations_count": 0,
  "tokens": { "input": 0, "output": 0, "total": 0 },
  "token_source": "provider|local_tokenizer|estimated",
  "latency_ms": 0.0,
  "trace": "TraceStep[] | null",
  "strategy_changed": "boolean|null",
  "stop_reason": "string|null",
  "status": "done|error",
  "error_detail": "string|null"
}
```
`trace`, `strategy_changed`, `stop_reason` are set for `agentic_graphrag` only.
`error_detail` is also set on a `done` record when a graph query failed during
the run (`"graph query error: <query>: <reason>"`): retrieval returned nothing
for that query, the answer keeps its status, and the failure is not mistaken
for "no evidence". In P3 the same text is appended to the `notes` of the trace
step that ran the query (`TigerGraphClient.drain_errors`, per thread).

### 6.3 TraceStep (agentic_graphrag only)

```json
{
  "step_n": 1,
  "agent_type": "orchestrator|entity_linking|graph_traversal|multi_hop_reasoning|aggregation|similarity_search|document_retrieval|evidence_evaluation|answer_generation",
  "tool_called": "intent_parser|entity_linker|Q1|Q2|Q3|Q4|Q1→Q4→Q1|Q4(HELD_AT)→Q1|Q5|HAS_CHUNK|evidence_evaluator|generate",
  "tokens": { "input": 0, "output": 0, "total": 0 },
  "chunks_returned": 0,
  "citations_count": 0,
  "latency_ms": 0.0,
  "strategy_change": false,
  "notes": "string"
}
```
`orchestrator` is the intent-parse (planning) step, recorded when it spent tokens; `answer_generation` is the final synthesis call. Every LLM call is a step, and Σ step tokens is asserted equal to the record total (`TraceRecorder.reconcile_assert`).

**`stop_reason` vocabulary** (`pipelines/p3_agentic/stopping.py`, closed): `sufficient_evidence`, `step_budget_exhausted` (`RUN_MAX_STEPS`), `token_budget_exhausted` (`RUN_MAX_TOKENS_PER_QUERY`), `no_further_action_available` (a loop traversal tool and both fallbacks tried), `disambiguation_required`, `error`, `direct_route` (a one-query lookup/aggregation route answered without the loop, so no evidence evaluation ran).

### 6.4 Batch record (`BatchRecord`)

```json
{
  "run_id": "string",
  "question_id": "string (= qid)",
  "question_text": "string",
  "qtype": "string|null",
  "ground_truth": ["string"],
  "gold_doc_ids": ["string"],
  "record": "QueryLevelRecord (§6.1)"
}
```
View records (`GET /batch/{run_id}/records`) add `qid`, `question` and backend-computed `scores` (§9.2).

## 7. Intent Schema (P2 and P3)

`pipelines/p3_agentic/intent.py`. Emitted via forced `emit_intent` tool call where tool calling is supported, else a JSON-schema prompt path (also retried once on that path when a provider rejects tool calling); schema-validated with one retry that carries the validation error back. A deterministic post-check for every provider: empty strings → null, numeric constraint strings → numbers, and a `venue` or `event_id` not present in the question is dropped as invented. `title`, `sport`, `games` are exempt (the model normalises them; the graph checks them). No question-template regex.

```json
{
  "operation": "LOOKUP | COUNT | ARGMAX | TRAVERSE",
  "anchor": { "sport": "string|null", "games": "string|null", "venue": "string|null", "title": "string|null", "event_id": "string|null" },
  "constraints": [ { "field": "string", "op": ">|<|=|>=|<=", "value": "number|string" } ],
  "target_field": "gold | nations | event_name | ... | null"
}
```

**Fully-specified anchor** ⇔ (`anchor.title` or `anchor.event_id` non-null) **and** `target_field` non-null **and** `constraints` empty.

**qtype → operation** (reporting only): lookup→LOOKUP · aggregation→COUNT · superlative→ARGMAX · temporal, multi_hop→TRAVERSE. `qtype` is never read at runtime (NFR-7).

Dispatch is `operation → query` per §3 — semantic parsing into a fixed vocabulary, not text-to-GSQL.

## 8. Pipeline Contracts

### 8.1 P1 — RAG (`pipelines/p1_rag.py`)

| Step | Detail |
|---|---|
| Retrieval | Query embedded with the model's query prefix (strict), Q5 top-`k` (10), **no filtering, no reranking** (AD-9) |
| Generation | One LLM call, shared answer contract |
| Output | answer, chunk citations, tokens, latency |

### 8.2 P2 — GraphRAG (`pipelines/p2_graphrag.py`)

| Step | Detail |
|---|---|
| Retrieval | Same intent parser and entity linker as P3, then exactly one graph query chosen by the same first-tool rule — no evidence check, no fallback, no loop |
| Generation | One LLM call with graph context (`contracts.format_evidence_context`) |
| Output | answer, entity/relationship citations, tokens, latency |

Ablation: **P1 removes the graph, P2 removes the loop, P3 has both.**

### 8.3 P3 — Agentic GraphRAG (`pipelines/p3_agentic/`)

| Step | Detail |
|---|---|
| Intent parse | §7 (trace `orchestrator` step) |
| Entity linking | Longest match against Games/Sport/Venue vocabularies. An ambiguous venue with no sport/event discriminator ends with `disambiguation_required`, candidates named in `answer` (≤10 shown) — no retrieval, no generation |
| Necessity routing | `router.route`: `lookup_direct`, `scoped_aggregate` (COUNT/ARGMAX, one Q2/Q3), or `loop` (ARCHITECTURE-SPEC §5) |
| Loop tools | `lookup` (Q1), `multi_hop` (Q1→Q4→Q1), `venue` (Q4 HELD_AT→Q1), `traversal` (Q4) |
| Evidence evaluation | Deterministic scope gate; groundedness by one LLM YES/NO call, gated for prose-only evidence by a deterministic token-overlap pre-check (structured evidence always gets the LLM check); an iteration with no new evidence reuses the previous verdict at 0 tokens |
| Fallbacks | scope fail → Q5 similarity search; groundedness fail → HAS_CHUNK document retrieval, reranked by the cross-encoder |
| Stopping | §6.3 vocabulary |
| Output | answer, citations, full trace, `strategy_changed`, `stop_reason`, cumulative tokens/latency |
| Context rendering | Shared with P2: prose chunks keep their text; structured rows render every non-empty field |

## 9. Evaluation

Source: `eval/scorer.py`, `common/names.py`. No LLM and no network in this path — deterministic run to run.

| Metric | Definition |
|---|---|
| Exact match (EM) | normalized **name set** of `answer` equals that of any gold variant (max over variants). A single-number gold (a count) also matches when the prediction states exactly one distinct number and it is that number (`"5 events"`, `"five"`); two different numbers do not |
| Token F1 | token overlap after the same normalization and name splitting, max over gold variants |
| Precision / Recall | returned document set (citation `source_id`s, deduplicated) vs `gold_doc_ids`; 0 when either is empty. No `@k` — undefined for P2/P3; `k = 10` applies to P1 retrieval only |
| Completeness | **= Recall**, kept as its own field because the guidebook names the column |
| Grounded | share of the answer's normalized names that occur, as whole words, in the normalized text of its own citations (`snippet`); 0 when nothing is cited. Needs no gold, so it is computed for hidden-set runs too (`view_record` → `grounding`) |
| Tokens / latency | provider-reported usage (§11) |
| Per-qtype breakdown | every metric by qtype (`aggregate_by_qtype`, missing qtype → `unknown`) |

### 9.1 Normalization and name splitting (`common/names.py`)

- `normalize_answer`: lowercase; apostrophes (`' ’ ʼ \``) removed (`Men's` → `mens`); accents folded (NFKD, combining marks dropped); every Unicode punctuation mark (dashes, quotes, …) → space; articles `a/an/the` dropped; whitespace collapsed; number words `zero`–`twenty` → digits; leading zeros dropped (`"05"` → `"5"`).
- `split_names`: split first on list separators `,` `;` `&` and the word `and`, then each part on lowercase→uppercase boundaries inside a word (concatenated names such as `Dani KingLaura Trott`), **unless** the word so far ends in a guarded prefix `Mac`, `Mc`, `Van`, `Di`, `De`, `Le`, `La`, `O'` (so `Rosannagh MacLennan` stays whole).
- EM compares `frozenset` of normalized names; an ordinary answer is a one-element set.

**Answer contract**: every pipeline uses the byte-identical `SHARED_SYSTEM_PROMPT`/`SHARED_USER_PROMPT` and returns `{"answer", "explanation"}`; only `answer` is scored. `parse_answer_contract_json` strips code fences and recovers `answer` from a truncated JSON reply.

### 9.2 Run summaries (`eval/history.py`)

`GET /runs` summarises each `out/*.jsonl` whose first line is a `run_config` header: `{run_id, status, started_at, dataset, run_config, n_questions, scored, pipelines}`. Per pipeline: `em`, `f1`, `precision`, `recall`, `completeness` (means over scored questions), `grounded` (mean over answered questions), `mean_tokens`, `median_tokens`, `total_tokens`, `mean_latency_ms`, `mean_input_tokens`, `mean_output_tokens`, `errors`, `f1_per_1k_tokens`. **Error records are excluded from the token and latency means** (an error carries 0 tokens and would make the most-failing pipeline look cheapest); they are counted in `errors`. A record without ground truth has `scores: null`. Scores are always recomputed from the answer when a record is read; stored or imported scores are never trusted. Unreadable run files are skipped. Imports are validated through the same summariser and the secret check before anything is written; history is never overwritten.

### 9.3 Batch store (`eval/store.py`)

Append-only JSONL, `{"run_config"}` header on line 1, one `BatchRecord` per line after it. Semantics:
- **Partial tail repair**: opening the store truncates an unfinished last line (no trailing newline and not valid JSON), so a killed run never buries a corrupt line mid-file; readers also skip an unfinished last line.
- **Resume**: questions whose latest record has no pipeline in `error` are skipped; **errored questions are retried**, and their new record is appended.
- **Last record per question wins** when reading (`read_run`), in file order of the latest.
- **Secret check** on every write (§14.3).

### 9.4 Hidden set

`acceptance/holdout/eval_hidden.jsonl` is run once by `make holdout`; CI's holdout grep (ARCHITECTURE-SPEC, Engineering guards) fails if any file under `backend/src`, `backend/tests` or `frontend/src` other than `eval/batch_runner.py` names `acceptance/holdout`. The hidden set has no gold answers, so its runs show `scores: null`.

## 10. Metrics Dashboard — Required Aggregations

| Chart/Table | Source fields |
|---|---|
| Per-qtype matrix (EM, F1, Recall, Precision, Completeness × 5 qtypes × 3 pipelines) | `scores`, `qtype` |
| Accuracy-vs-tokens scatter | `tokens.total` vs EM/F1, per pipeline |
| Agentic step-count distribution | `trace.length` |
| Strategy-change frequency | `strategy_change: true` |
| Stop-reason breakdown | `stop_reason` |
| Trace viewer | full `TraceStep[]` for a selected question |
| Eval table | one row per question × 3 pipelines, gold answer and `gold_doc_ids` beside them |

Screen detail: `UI-SPEC.md`.

## 11. Non-Functional Implementation Notes

| Concern | Implementation note |
|---|---|
| Concurrency | `eval/dispatcher.dispatch` (batch) and `_run_query` (API) run the three pipelines with `asyncio.gather`, each in a worker thread |
| Latency comparability | Run modes (`ogr.cli batch --mode`, `POST /batch latency_mode`, default `RUN_LATENCY_MODE`): `throughput` = pool `RUN_POOL_SIZE` (default 2) for accuracy/tokens (pool-invariant); `timing` = pool 1 for latency. The header records mode and effective pool |
| Rate limiting | One `InMemoryRateLimiter` per cached client (`LLM_REQUESTS_PER_MINUTE`, 0 = off). `invoke_and_count` retries on HTTP 408/409/429/5xx/529 and connection/timeout/overload error names, exponential backoff from `LLM_BACKOFF_BASE_S` with jitter, `Retry-After` honoured, up to `LLM_MAX_RETRIES`; SDK retries are off. A per-day quota (`PerDay`) is not retried. An exhausted rate limit raises `LLMRateLimitError` naming provider/model; there is never a fallback to another provider. Gemini `LLM_THINKING` (default `minimal`) — thinking tokens count against `LLM_MAX_TOKENS`. Only the successful call's tokens count; `latency_ms` includes the waits |
| Sampling seed | `RUN_SEED` passed as `seed` to OpenAI-compatible and Gemini clients (ignored with a warning for Anthropic), recorded in the header |
| Fault isolation | Each pipeline call is wrapped; an exception becomes `error_record(pipeline, detail)` (`status: error`), the other two records are still returned |
| Instrumentation | Usage from `usage_metadata`/`token_usage` (`token_source: provider`); else the model's tokenizer (`local_tokenizer`); else chars/4, labelled `estimated`. `LLM_REPORTS_TOKEN_USAGE=false` skips provider usage |
| Reproducibility | `run_config` header in every run file (§4.3); query and index use the same model key |
| GSQL install cost | Installing takes minutes and blocks concurrent operations; installed once per build |
| Vector readiness gate | Build and re-embed jobs wait for `Ready_for_query` (§3); a model is marked complete only once its index is queryable; `cli build` exits 1 on timeout |
| Embedding strictness | Every index write and every query embedding is strict (`EmbeddingUnavailable` instead of hash noise) |
| Secrets | §14.3 |

## 12. Deployment and Reproduction

### 12.1 Makefile

`RUN_ID` defaults to one UTC timestamp for the whole invocation; `OGR := python3 -m ogr.cli`.

| Target | Command |
|---|---|
| `install` | `pip install -e "backend[dev]"`; `cd frontend && npm ci` |
| `check` | `ruff check src tests && pytest -q` (backend); `npm run lint && npm run build && npm test` (frontend) |
| `verify` | `ogr.cli verify --pre-build` (missing GSQL queries reported as WARN, not a failure) |
| `build` | `ogr.cli build` (default corpus `data/corpus/corpus.jsonl`) |
| `benchmark` | `batch data/questions/eval_public.jsonl --mode throughput --run-id $(RUN_ID)-public --out out/$(RUN_ID)-public.jsonl` |
| `timing` | same set, `--mode timing`, `$(RUN_ID)-public-timing` |
| `holdout` | `batch acceptance/holdout/eval_hidden.jsonl --mode throughput`, `$(RUN_ID)-holdout` |
| `results` | `ogr.cli report out/$(RUN_ID)-public.jsonl --out …-public-report.md`; `ogr.cli export out/$(RUN_ID)-holdout.jsonl --out …-holdout-export.json` |
| `reproduce` | all of the above in order |
| `smoke` | one `ask` through all three pipelines with `--show-trace` (not part of `reproduce`) |

### 12.2 CLI (`python -m ogr.cli`, `backend/src/ogr/cli.py`)

| Command | Behaviour |
|---|---|
| `verify [--pre-build]` | Prints config (secrets masked) and LLM, Embedding, TigerGraph, GSQL-queries checks; exit 1 on any FAIL |
| `build [--corpus PATH] [--vector-timeout 600]` | Chunk + strict embed with the embedding store's active model (else `EMBEDDING_MODEL`), **install schema (resets the graph and every dataset)**, reset registry and store, load, install Q1–Q5, wait for the index |
| `batch QUESTIONS --out PATH [--run-id ID] [--mode throughput\|timing] [--embedding-model KEY]` | Same runner as `POST /batch`; exit 1 on `BatchIncompleteError` or `LLMRateLimitError`; rerun resumes |
| `ask QUERY [--pipelines rag,graphrag,agentic_graphrag] [--embedding-model KEY] [--json] [--show-trace]` | Aliases `graph`, `agentic`; default `rag` |
| `coverage [--corpus PATH] [--out out/ingest-coverage.md]` | Infobox parse coverage report |
| `report RUN [--out PATH]` | `eval/report.py` `build_report`: headline (EM, F1, completeness, grounded, tokens, latency, errors); per qtype the Agentic − RAG EM gap, median Agentic ÷ RAG token ratio and verdict (dashboard thresholds 0.5 / 0.05); win/loss question ids; necessity routing (`stop_reason == "direct_route"` vs loop) with a labelled estimate of tokens saved; agent/tool/stop-reason mix |
| `export RUN --out PATH` | `export_run`: `{run_id, run_config, questions: [{qid, question, qtype, pipelines: {<name>: {answer, explanation, status, tokens, token_source, latency_ms, chunks_returned, citations, + trace, strategy_changed, stop_reason for agentic}}}]}` |

### 12.3 Other

API server: `python -m uvicorn ogr.api.main:app --app-dir backend/src --host 127.0.0.1 --port 8000` (host/port are uvicorn flags, not env vars). Windows launcher: `run.bat`. Hosting: `DEPLOY.md`. Corpus attribution (CC BY-SA 4.0): `ATTRIBUTION.md`.

## 13. Technical Decisions — all closed

Rationale and rejected alternatives: ARCHITECTURE-SPEC.md, **Decision log**.

| Decision | Status |
|---|---|
| Backend framework | Python 3.11 + FastAPI + `sse-starlette` |
| Frontend framework | React + Vite |
| Streaming transport | SSE; `POST → 202`, `GET …/stream?token=` |
| Ground-truth scoring | deterministic EM/F1, no LLM judge |
| Embedding model | five selectable, ≤ 2 stored, per-model vertex types + HNSW indices (`EMBEDDING-SWITCHING.md`) |
| LLM provider | pluggable, one boundary, pinned per run; runtime presets; no cross-provider fallback |
| Reranker | Cloudflare cross-encoder, P3 fallback prose only |
| Batch output storage | append-only JSONL per run, `run_config` header |
| Multi-dataset graph | all datasets in one graph, per-dataset id registry, rebuild/reset explicit |
| Trace-as-graph write-back | cut |
| P2 routing | reuses P3's parser, single query, no loop |
| Answer contract | shared `{answer, explanation}`, EM/F1 score `answer` |
| Latency measurement | `throughput` / `timing` run modes |

## 14. Configuration

Structure follows `tigergraph/graphrag`'s `server_config.json` (`db_config` / `llm_config` / service sections). No secret is ever written to a config file.

**Precedence** (`common/config.py` `_env`): environment (`.env`, loaded by `python-dotenv`) > `config/server_config.json` > code default. Only the variables mapped in `_FILE_KEYS` can come from the file; hosts, provider, model, base URL and credentials come only from the environment.

### 14.1 `config/server_config.json` (committed, no secrets)

```json
{
  "db_config": { "graphname": "OlympicGraphRAG", "useCert": true, "certPath": null },
  "llm_config": {
    "completion_service": {
      "model_kwargs": { "temperature": 0, "max_tokens": 1024 },
      "supports_tool_calling": "auto",
      "reports_token_usage": "auto",
      "thinking_level": "minimal"
    },
    "embedding_service": {
      "embedding_model_service": "cloudflare, local (first available)",
      "model_name": "bge-large-en-v1.5",
      "similarity": "COSINE"
    },
    "rate_limit": { "max_concurrent": 2, "requests_per_minute": 30, "backoff_base_s": 2, "max_retries": 5 },
    "nvidia_free_endpoints": {
      "catalog_url": "https://api.ngc.nvidia.com/v2/search/catalog/resources/ENDPOINT",
      "catalog_query": "{\"query\": \"\", \"page\": 0, \"pageSize\": 1000, \"filters\": [{\"field\": \"nimType\", \"value\": \"nim_type_preview\"}]}"
    }
  },
  "api_config": { "stream_token_ttl_s": 300 },
  "run_defaults": {
    "k": 10, "chunk_tokens": 300, "chunk_overlap": 50, "max_steps": 6,
    "max_tokens_per_query": 20000, "max_total_tokens": 5000000, "latency_mode": "throughput", "seed": null
  }
}
```

File key → env var: `db_config.graphname` TG_GRAPHNAME · `useCert` TG_USE_CERT · `certPath` TG_CERT_PATH · `model_kwargs.temperature` LLM_TEMPERATURE · `max_tokens` LLM_MAX_TOKENS · `thinking_level` LLM_THINKING · `supports_tool_calling` LLM_SUPPORTS_TOOL_CALLING · `reports_token_usage` LLM_REPORTS_TOKEN_USAGE · `nvidia_free_endpoints.catalog_url/catalog_query` NVIDIA_FREE_CATALOG_URL/_QUERY · `embedding_service.model_name` EMBEDDING_MODEL · `rate_limit.max_concurrent` RUN_POOL_SIZE · `requests_per_minute` LLM_REQUESTS_PER_MINUTE · `backoff_base_s` LLM_BACKOFF_BASE_S · `max_retries` LLM_MAX_RETRIES · `api_config.stream_token_ttl_s` OGR_STREAM_TOKEN_TTL_S · `run_defaults.*` RUN_K, RUN_CHUNK_TOKENS, RUN_CHUNK_OVERLAP, RUN_MAX_STEPS, RUN_MAX_TOKENS_PER_QUERY, RUN_MAX_TOTAL_TOKENS, RUN_LATENCY_MODE, RUN_SEED. `embedding_model_service` and `similarity` are descriptive only (not read). `supports_tool_calling`/`reports_token_usage` accept `auto`, `true`, `false`.

### 14.2 Environment variables (`env.example`, backend)

Defaults are the effective ones (file value where the file sets one, else code).

| Group | Variable | Default / note |
|---|---|---|
| TigerGraph | `TG_HOST` | `http://localhost` (Savanna: workspace endpoint) |
| | `TG_GRAPHNAME` | `OlympicGraphRAG` |
| | `TG_CLOUD` | `false` in code (`env.example`: `true`) — must be `true` for Savanna |
| | `TG_RESTPP_PORT`, `TG_GS_PORT` | unset; set 14240 etc. for CE only (Savanna derives 443) |
| | `TG_JWT_TOKEN` › `TG_TOKEN` › `TG_SECRET` › `TG_USERNAME`/`TG_PASSWORD` | first non-empty wins; username default `tigergraph` |
| | `TG_USE_CERT`, `TG_CERT_PATH` | `true`, unset |
| Runtime LLM presets | `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY` | env only (§14.4) |
| | `NVIDIA_FREE_CATALOG_URL`, `NVIDIA_FREE_CATALOG_QUERY` | from the file |
| Startup LLM | `LLM_PROVIDER` | `openai_compatible` (`env.example`: `openai`) |
| | `LLM_MODEL` | `qwen2.5:7b-instruct` (`env.example`: `gpt-4o-mini`) |
| | `LLM_BASE_URL` | `http://localhost:11434/v1` when unset; an empty value in `.env` means none |
| | `LLM_API_KEY` | none |
| | `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_THINKING` | 0, 1024, `minimal` |
| | `LLM_SUPPORTS_TOOL_CALLING`, `LLM_REPORTS_TOKEN_USAGE` | `auto` |
| | `LLM_REQUESTS_PER_MINUTE`, `LLM_BACKOFF_BASE_S`, `LLM_MAX_RETRIES` | 30 (code default 0 if the file is absent), 2, 5 |
| Embeddings | `EMBEDDING_MODEL` | `bge-large-en-v1.5`; a catalog key, label, HF id or Cloudflare id; an unknown value logs a warning and uses the default. Startup default only — the embedding store's active model wins. Dimension follows the model (no `EMBEDDING_DIM` variable) |
| | `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | env only; also serve the reranker; empty or failing → the same model locally (embeddings: `sentence-transformers`; reranker: `BAAI/bge-reranker-base` `CrossEncoder`) |
| | `EMBEDDING_HOST_URL` | unset; a self-hosted `POST {url}/embed {"model","texts"} → {"embeddings"}` service, tried first |
| | `EMBEDDING_CLOUDFLARE`, `EMBEDDING_REMOTE` | `true`; `false` skips the Cloudflare tier / every remote tier. Tier order: host → Cloudflare → local → hash (non-strict only) |
| Run | `RUN_K`, `RUN_CHUNK_TOKENS`, `RUN_CHUNK_OVERLAP`, `RUN_MAX_STEPS`, `RUN_MAX_TOKENS_PER_QUERY`, `RUN_POOL_SIZE`, `RUN_LATENCY_MODE`, `RUN_MAX_TOTAL_TOKENS`, `RUN_SEED` | 10, 300, 50, 6, 20000, 2, `throughput`, 5000000, none |
| API | `OGR_API_KEY` | required; unset → every protected route 503 |
| | `OGR_STREAM_TOKEN_TTL_S` | 300 |
| | `OGR_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |
| | `HEALTH_LLM_TIMEOUT_S` | 120 |

There is no `OGR_HOST`/`OGR_PORT`; bind address and port are uvicorn arguments (§12.3).

**Frontend** (build-time, `frontend/.env.example`; Vite exposes only `VITE_*`): `VITE_API_BASE_URL` (`http://127.0.0.1:8000`), `VITE_API_KEY` (sent as `X-API-Key`), `VITE_USE_MOCK_API` (only the string `true`, case-insensitive, enables the fixture transport; default `false`), `VITE_MOCK_LATENCY_SCALE` (1), `VITE_DEFAULT_RUN_ID`, `VITE_ADMIN_EMAIL`, `VITE_POLL_INTERVAL_MS` (600000). Details: `UI-SPEC.md`.

### 14.3 Rules

| Rule | Reason / enforcement |
|---|---|
| `.env` is git-ignored; `env.example` and `frontend/.env.example` are committed with empty secrets | shape is documentation, values are secrets |
| No credential in `server_config.json`, a persisted record, an SSE frame, a log or an unauthenticated response | `eval/store._assert_no_secret` on every header, record and import: key shapes (`sk-`, `gsk_`, `AIza`, `hf_`, `gh[pousr]_`, JWT) plus the literal values (≥ 8 chars) of `LLM_API_KEY`, `TG_PASSWORD`, `TG_SECRET`, `TG_TOKEN`, `TG_JWT_TOKEN`, `OGR_API_KEY`. The run header is an explicit allow-list. Health details are redacted (§4.7); `GET /settings` exposes only the base host |
| `run_config` is written into every run's header | a result without its conditions is not reproducible (NFR-4) |
| The model is pinned within a run, swappable between runs | each query/run snapshots the config once; P1/P2/P3 share one cached client |
| `VITE_API_KEY` ships to the browser and is **not a secret** | protects against casual access; keep the API bound to `127.0.0.1` unless deployed deliberately (`DEPLOY.md`) |
| Changing provider is a `.env` edit or a Settings preset — no code change | single boundary `common/llm.py` |

### 14.4 Runtime LLM presets (`common/llm.py` `PROVIDER_PRESETS`)

| Preset | Label | Client | Base URL | Model list URL | Key |
|---|---|---|---|---|---|
| `gemini` | Google Gemini (AI Studio) | native `ChatGoogleGenerativeAI` | — | `https://generativelanguage.googleapis.com/v1beta/openai/models` | `GEMINI_API_KEY` |
| `nvidia_nim` | NVIDIA NIM | OpenAI-compatible | `https://integrate.api.nvidia.com/v1` | `…/v1/models` | `NVIDIA_API_KEY` |
| `groq` | Groq | OpenAI-compatible | `https://api.groq.com/openai/v1` | `…/openai/v1/models` | `GROQ_API_KEY` |

- `GET /settings/models` lists the live catalog (explicit User-Agent; Groq's CDN rejects urllib's default), drops non-text models by type regex (embed, rerank, speech, image, OCR, guard, …); Gemini keeps `flash` models only (Flash, Flash-Lite).
- NVIDIA is narrowed to models the NGC catalog labels "Free Endpoint" (`NVIDIA_FREE_CATALOG_*`, cached 1 h). If the filter is not configured, fails or matches nothing, every text model is returned with an explicit `note`.
- `PATCH /settings` with a provider requires a model and the preset's key on the server; it sets provider, base URL and key as in-memory overrides (lost on restart) and clears the model cache. The selection applies to all three pipelines.
- `GET /settings` reports `llm_provider_preset` by matching the provider name or the base URL host against the presets.
