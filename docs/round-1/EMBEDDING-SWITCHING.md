# Embedding model switching

How the three pipelines (RAG, GraphRAG, Agentic GraphRAG) switch between five
embedding models on TigerGraph without ever searching one model's index with
another model's query vector.

Scope: one global corpus. Embeddings must cover every chunk in the graph (the
union of the dataset registry's `chunk_ids`); there is no per-collection
tracking. Per-dataset tracking could reuse the same design later.

## 1. Models

`backend/src/ogr/common/embedding_models.py` is the one catalog. A model is
identified by its **key**, never by its dimension.

| Key | Label | Dim | Vertex type | Served by |
|---|---|---|---|---|
| `qwen3-embedding-0.6b` | Qwen3-Embedding-0.6B | 1024 | `Embedding_Qwen` | local sentence-transformers |
| `embeddinggemma-300m` | EmbeddingGemma-300M | 768 | `Embedding_EmbeddingGemma` | local (gated on Hugging Face: accept the licence, set `HF_TOKEN`) |
| `gte-large-en-v1.5` | gte-large-en-v1.5 | 1024 | `Embedding_GteLarge` | local (`trust_remote_code`) |
| `mxbai-embed-large-v1` | mxbai-embed-large-v1 | 1024 | `Embedding_Mxbai` | local |
| `bge-large-en-v1.5` (default) | bge-large-en-v1.5 | 1024 | `Embedding_BGELarge` | Cloudflare `@cf/baai/bge-large-en-v1.5` with `pooling: "cls"`, falls back to local |

Cloudflare's bge models default to mean pooling, while BGE and the local
sentence-transformers model use CLS pooling. The request pins CLS, so both
tiers produce vectors in the same space and a per-batch fallback cannot mix
two spaces in one index.

Each model's query and document prompts from its model card (for example
Qwen3's `Instruct: … Query:` and EmbeddingGemma's `task: search result |
query:`) are applied in `common/embeddings.py`.

**Strict embedding.** Anything that writes to an index (builds, re-embed
jobs) and every query embedding (P1 and the P3 similarity agent) call the
embedder with `strict=True`. If no real host can serve the model, it raises
`EmbeddingUnavailable` instead of returning the old hash-fallback vector.
Hash noise is never stored or searched as a model's embeddings. The hash
fallback stays only for non-strict callers, such as tests and the benchmark
header's backend probe.

## 2. Storage schema

```
Document ──HAS_CHUNK──▶ Chunk (chunk_id, doc_id, text, seq, token_count)   ← stored once, no vector
                          │
                          ├─HAS_EMBEDDING─▶ Embedding_Qwen            (PRIMARY_ID chunk_id, emb[1024]) ─ HNSW
                          ├─HAS_EMBEDDING─▶ Embedding_EmbeddingGemma  (PRIMARY_ID chunk_id, emb[768])  ─ HNSW
                          ├─HAS_EMBEDDING─▶ Embedding_GteLarge        (PRIMARY_ID chunk_id, emb[1024]) ─ HNSW
                          ├─HAS_EMBEDDING─▶ Embedding_Mxbai           (PRIMARY_ID chunk_id, emb[1024]) ─ HNSW
                          └─HAS_EMBEDDING─▶ Embedding_BGELarge        (PRIMARY_ID chunk_id, emb[1024]) ─ HNSW
```

`backend/src/ogr/graph/schema.gsql`:

- `Chunk` and `OlympicEvent` no longer carry `emb`. `OlympicEvent.emb` was
  never populated by the loader.
- There are five `Embedding_*` vertex types. The **primary id is the chunk_id
  it embeds**, so a model has at most one embedding per chunk by
  construction.
- `HAS_EMBEDDING` is one directed edge type with a `FROM Chunk, TO
  Embedding_*` pair per model, and `reverse_HAS_EMBEDDING` for the way back.
- One `ADD VECTOR ATTRIBUTE emb(DIMENSION=<model dim>, METRIC="COSINE")` per
  embedding type gives each model its **own HNSW index**.
- All five types always exist, so the installed Q5 always compiles. A model
  that is not stored has zero vertices, and so an empty index.
  `tests/graph/test_schema.py` checks the file against the catalog.

**Query flow.** `graph/queries/q5_hybrid_search.gsql` takes `emb_type`.
Each branch runs `vectorSearch({Embedding_X.emb}, …)` only on its own type,
collects the hits, and traverses `reverse_HAS_EMBEDDING` to the canonical
`Chunk` for text and doc_id. An unknown `emb_type` matches no branch and
returns nothing; it never falls through to another model's index. Distances
are keyed by embedding vertex, whose id is the chunk_id, so the client's
existing join is unchanged.

## 3. State and completeness

`backend/src/ogr/ingest/embedding_index.py` keeps `out/embeddings.json`
(runtime state, next to `out/datasets.json`):

```json
{"active": "bge-large-en-v1.5",
 "models": {"bge-large-en-v1.5": {"covered": ["Q1_c0", "…"], "backend": "cloudflare", "evicting": false}},
 "job": {"model": "…", "mode": "parallel", "delete": [], "status": "failed", "phase": "embedding",
         "batches_done": 12, "batches_total": 34, "chunks_done": 6000, "chunks_total": 16741, "error": "…"}}
```

- **Stored** means the model has an entry. Its slot is reserved when its job
  starts, which is what counts against the cap. A model being evicted is not
  counted, because its deletion runs first in the next job.
- **`covered`** is the set of chunk ids whose embedding is written *and*
  checkpointed.
- A model is **complete** when it covers every corpus chunk, no job is
  running or failed on it, and it is not being evicted. Only complete models
  are queryable.
- The states shown in the UI are `complete`, `incomplete` (n/m chunks),
  `building`, `failed`, `evicting`, `indexing` and `not_stored`.
- **`indexing`** means the vectors are written but the index is not yet
  confirmed queryable. A build records coverage right after its load, and
  clears the flag when the index reports ready. If the build fails in
  between, **Complete** only waits for the index; it does not re-embed.
- **Active** is the model queries use by default.
  `_get_config_with_overrides` sets `embedding_model` and `embedding_dim`
  from it for every route. `EMBEDDING_MODEL` is only the first default.

## 4. Switching (Settings → Knowledge Base · Embedding Model)

The five models are listed with their state. Choosing a model other than the
active one calls `GET /embeddings/plan?model=…`, whose answer comes from the
current state. What happens next depends on that plan:

- **The target is already complete.** The switch is instant: a confirm, then
  `POST /embeddings/switch {model}`. No job runs and nothing is deleted.
- **Otherwise.** The dialog shows two options, **with neither preselected**.
  The confirm button stays disabled until one is chosen, and the server
  refuses a switch without `mode` (`409 mode_required`).

  | | Force full re-embed (`mode: "replace"`) | Keep parallel indices (`mode: "parallel"`) |
  |---|---|---|
  | What happens | The outgoing (active) model's embeddings are deleted, then the new model embeds the corpus | The new model builds alongside; the active model stays active until the new one is complete, then the new one becomes active |
  | Pro | No extra storage; any other stored model stays queryable | The old model stays queryable immediately; switching back later is instant |
  | Con | Blocking: queries with the new model are refused until it is complete; returning to the old model means re-embedding it | Extra TigerGraph storage and index-build time (one more HNSW index); counts toward the cap |

The dialog text uses the real numbers: stored count against the cap (for
example "2/2 models currently stored: Qwen3-Embedding-0.6B,
bge-large-en-v1.5 (active)"), the chunk count, the model that would be
deleted and the model that would be kept.

## 5. Cap and eviction (max 2 models)

`MAX_STORED_MODELS = 2`, enforced in `EmbeddingStore.begin_switch`.

- **Parallel with 2 other models stored.** The request must name `evict`,
  one of those two. Without it the server answers `409 eviction_required`
  with the `evictable` list, and no job is recorded. In the dialog the
  eviction picker is mandatory and the confirm stays disabled until a model
  is picked.
- **An `evict` that isn't allowed or isn't needed** is refused
  (`invalid_eviction`, `eviction_not_needed`).
- **Eviction happens before embedding.** The job's first phase deletes the
  evicted model, and embedding starts only after that deletion returns. If
  the deletion fails, the job is failed, nothing has been embedded, and a
  resume retries the deletion.
- **Evicting the active model** is allowed. The new model becomes active at
  once, and queries wait for it or use the other complete model through the
  mismatch popup.
- **A failed eviction is never left half done.** A new switch carries the
  failed job's pending deletions into its own job, where they run first.
  Switching back to a model whose eviction failed re-embeds it from scratch,
  because its remaining vectors can't be trusted.
- **Builds respect the cap too.** A build refuses (`409 embedding_cap`) in
  the one state where it could add a third model: a switch that failed
  mid-eviction.

## 6. What a deletion touches

`TigerGraphClient.delete_embeddings(model, chunk_ids=None)` is the only
deletion path for embeddings (eviction, the replaced model, and a dataset
rebuild's removed chunks):

- It calls `delVertices(<model's Embedding_X>)`. For given chunk ids it runs
  one interpreted GSQL query per 200 ids (`to_vertex_set` + `DELETE`), and
  falls back to `delVerticesById` if the server refuses interpreted mode;
  pyTigerGraph sends one REST call per id. Chunk texts for a job are read
  the same way. The type comes from the catalog and is re-checked
  (`_embedding_type`), so a deletion can never be pointed at `Chunk` or any
  non-embedding type.
- Deleting a vertex in TigerGraph removes only the edges touching it. That
  removes the model's vectors (emptying its HNSW index) and its own
  `HAS_EMBEDDING` edges. **Canonical chunks, `HAS_CHUNK`, and every other
  model's vertices and edges are untouched.** Nothing ever deletes a `Chunk`
  to remove embeddings.
- The vertex type and its vector attribute *declaration* remain, empty,
  because the installed Q5 references all five types. Dropping the type would
  break Q5 and need a query reinstall. What eviction frees is the data: all
  vectors, index entries and edges.
- **Dataset rebuild.** Deleting a dataset's `Chunk` vertices would leave
  orphaned `Embedding_*` vertices, since only the edge goes. So the rebuild
  first deletes those chunk ids from every stored model and removes them from
  `covered`.

Tested against an in-memory graph with TigerGraph's deletion rule
(`tests/graph/fake_tigergraph.py`): eviction, replace and partial deletes
leave the chunks, `HAS_CHUNK` and the other model's vertices and edges
intact, and a forged model pointing at `Chunk` is refused before any call.

## 7. Query-time block

`_query_config` in `api/main.py` runs before `POST /query` starts anything,
and before `POST /batch`:

- The selected model is the request's `embedding_model`, or the active one.
- If that model is not complete, the server answers **`409
  embedding_mismatch`**. The response carries a message saying why (not
  stored, still building, failed, incomplete n/m, being evicted), a
  `selected` status, and `available`: every model that is complete.
- The UI (`SearchView` → `EmbeddingMismatchDialog`) blocks the query, states
  that the selected model has no matching embeddings, and lists the
  `available` models. Picking one re-submits the same query with
  `embedding_model` set to it. There is no "run anyway".
- **By identity, not dimension.** Completeness is looked up by model key. A
  query for Qwen3 is blocked even when bge-large (also 1024-dim) is
  complete; `tests/api/test_embeddings_api.py` checks exactly that.
- **Inside a pipeline** the same `config.embedding_model` picks both the
  query embedding (`embed_query(model_name=…)`) and the index
  (`hybrid_search(embedding_model=…)` → `emb_type`). As a second guard,
  `hybrid_search` raises if the vector length differs from that model's
  dimension, and `upsert_embeddings` and `load_graph` refuse vectors of the
  wrong size.

## 8. Jobs: checkpoint, resume, failure

`run_job` (in `ingest/embedding_index.py`) runs in a worker thread started by
`POST /embeddings/switch`, `/embeddings/resume` or
`/embeddings/{model}/complete`. It has three phases:

1. **Deleting.** Remove the replaced or evicted models (section 6).
2. **Embedding.** Take `corpus − covered`, sorted, in batches of
   `CHECKPOINT_BATCH = 500`, the build's own embedding step. For each batch:
   read the chunk texts from the graph, embed strictly, upsert the
   `Embedding_X` vertices and `HAS_EMBEDDING` edges, then **checkpoint** by
   adding the batch to `covered`.
3. **Indexing.** Wait for the vector index to be `Ready_for_query`. Only
   then is the model complete, and a parallel job makes it active.

Failure and resume:

- **Any exception** (network error, 429, index timeout) marks the job
  `failed` with its error and phase. It is never swallowed and never
  restarted from scratch. Every finished batch is already in `covered`.
- **Resume** (`POST /embeddings/resume`) runs the same job again. The
  deletions are skipped if already done, and the embedding step recomputes
  `corpus − covered`, so it continues from the last checkpointed batch.
  Tested: a 429 on batch 2 of 3 resumes with 4 of 7 chunks, not 7.
- **Idempotent.** A batch whose upsert landed but whose response was lost is
  not checkpointed, so a resume writes it again onto the same primary ids
  (`chunk_id`). Nothing is duplicated; tested with exact vertex and edge
  counts.
- **Server restart.** A job recorded as `running` whose task is gone is
  recorded as `failed` ("Interrupted by a server restart") on the next
  request. That makes it resumable and stops it blocking switches and
  queries. The job slot is held from the moment a job is recorded until its
  task exists, so this recovery can't catch a job that is just starting.
- **What Settings shows.** The job line reads running (phase, batch n/m,
  chunks), failed with its error and a **Resume** button, or complete. Each
  model shows its state. A stored model that lacks chunks, because a dataset
  was built while another model was active, shows `incomplete` with a
  **Complete** button that embeds only the missing chunks.

## 9. Server-side enforcement

The UI disables the switch and explains why. Every rule below is also
enforced by the server, so a stale or concurrent UI cannot get around it.

| Condition | Refused | Code |
|---|---|---|
| Ingestion build running | `/embeddings/switch`, `/resume`, `/{model}/complete`, `PATCH /settings {embedding_model}` | `build_running` |
| Re-embed job running | the same, and `POST /build`, `POST /batch` | `embedding_job_running` / `busy` |
| Benchmark run in progress | `/embeddings/switch`, `/resume`, `/{model}/complete`, `POST /build` | `batch_running` |
| Target not complete, no `mode` | `/embeddings/switch` | `mode_required` |
| `PATCH /settings` to a model that is not complete | `PATCH /settings` | `embedding_switch_required` |
| At the cap, no or invalid `evict` | `/embeddings/switch` | `eviction_required`, `invalid_eviction` |
| Selected model not complete | `POST /query`, `POST /batch` | `embedding_mismatch` |
| Graph built with the old single-vector layout | `POST /build` without reset | `reset_required` |

`GET /embeddings` reports `build_running` and `switch_disabled_reason`, and
the panel polls every 3 s while a build or job runs, so the control
re-enables by itself. Builds, runs and jobs reserve their slot before their
first `await`, so two requests can't both pass a "nothing is running" check.

## 10. Builds

A build embeds with the **active** model only, strictly, in 500-chunk steps.
It writes canonical `Chunk` vertices plus that model's `Embedding_X` vertices
and `HAS_EMBEDDING` edges. It adds the chunks to `covered` as `indexing`
right after the load, and the model becomes complete only once the vector
index is ready. A reset build clears the embedding state along with
the graph. Another stored model is not re-embedded by a build; it shows
`incomplete` and is completed from Settings.

## 11. Implementation plan (as applied)

| # | Change | File / module |
|---|---|---|
| 1 | Model catalog: keys, labels, dims, vertex types, prompts, hosts, cap | `backend/src/ogr/common/embedding_models.py` (new) |
| 2 | Per-model embedding with prompts, dimension check, `strict` mode | `backend/src/ogr/common/embeddings.py` |
| 3 | `EMBEDDING_MODEL` normalized to a catalog key; dim from the model | `backend/src/ogr/common/config.py`, `env.example`, `config/server_config.json` |
| 4 | Schema migration: vector-free `Chunk`; five `Embedding_*` types; `HAS_EMBEDDING`; one HNSW per type | `backend/src/ogr/graph/schema.gsql` |
| 5 | Q5 searches `emb_type`'s own index, returns chunks via `reverse_HAS_EMBEDDING` | `backend/src/ogr/graph/queries/q5_hybrid_search.gsql` |
| 6 | `hybrid_search(embedding_model)`, `upsert_embeddings`, `delete_embeddings` (type-guarded), `get_chunk_texts` | `backend/src/ogr/graph/client.py` |
| 7 | Loader writes each vector to the model's type, never to `Chunk` | `backend/src/ogr/ingest/load.py`, `ingest/chunk_embed.py` |
| 8 | Layout marker and corpus chunk set | `backend/src/ogr/ingest/registry.py` |
| 9 | State store, plan, cap and eviction, checkpointed resumable job | `backend/src/ogr/ingest/embedding_index.py` (new) |
| 10 | `/embeddings`, `/plan`, `/switch`, `/resume`, `/{model}/complete`; mutual exclusion with builds; query and batch block; build integration | `backend/src/ogr/api/main.py`, `backend/src/ogr/cli.py` |
| 11 | Pipelines pass the model key to the search; strict query embedding | `pipelines/p1_rag.py`, `pipelines/p3_agentic/agents/similarity_search.py` |
| 12 | Health check reports the active model's tier | `backend/src/ogr/verify.py` |
| 13 | Settings section: states, disabled reason, job status, Resume and Complete | `frontend/src/components/EmbeddingSettings.tsx` (new), `SettingsPanel.tsx`, `services/settingsService.ts` |
| 14 | Informed-decision dialog with mandatory eviction | `frontend/src/components/EmbeddingSettings.tsx` (`EmbeddingSwitchDialog`) |
| 15 | Query-time mismatch popup and re-run with the picked model | `frontend/src/components/EmbeddingMismatchDialog.tsx` (new), `SearchView.tsx`, `services/queryService.ts`, `services/http.ts` |
| 16 | Tests | `tests/ingest/test_embedding_index.py`, `tests/api/test_embeddings_api.py`, `tests/graph/fake_tigergraph.py`, `tests/graph/test_schema.py`, `tests/common/test_embeddings.py`, `tests/ingest/test_load.py`; frontend `EmbeddingSettings.test.tsx`, `SearchView.test.tsx` |

## 12. Verification status and limits

- **Tested** (backend pytest, frontend vitest): cap and eviction rules;
  replace and eviction deletion scope against a TigerGraph-semantics fake;
  checkpoint resume skipping finished batches; idempotent re-write of a
  partially written batch; index-wait failure resumes without re-embedding;
  query and batch block, including equal dimensions; server-side refusals
  during a build; an end-to-end parallel switch through the API. The UI was
  also driven in a browser against a local backend: dialog, mandatory
  eviction, and a real failed-then-resumable job.
- **Not verified against a live TigerGraph.** The GSQL is checked only by
  static tests: the multi-pair `HAS_EMBEDDING`, the `ELSE IF` chain and
  `{@@hits}` vertex set in Q5, and the five-attribute schema-change job. The
  first real `install_schema` + `install_queries` is their syntax check.
  `install_queries` fails the build loudly if Q5 does not install.
- **Migration.** A graph built before this change keeps its vectors on
  `Chunk`. `POST /build` answers `reset_required` until a reset build
  recreates it. `@cf/baai/bge-m3` is no longer selectable; a leftover
  `EMBEDDING_MODEL=@cf/baai/bge-m3` falls back to `bge-large-en-v1.5` with a
  warning.
- **Weights.** Only bge-large-en-v1.5 has a Cloudflare tier. The other four
  need their weights available to sentence-transformers on the server
  (EmbeddingGemma needs Hugging Face licence acceptance). Without the
  weights, strict embedding fails the job or query with a clear error.
