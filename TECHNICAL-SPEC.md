# TECHNICAL-SPEC.md
Agentic GraphRAG Hackathon — Three-Pipeline Comparison System

Status: **v0.3 — synchronised with implementation plans, 2026-09-21.** Supersedes v0.2. | Standard basis: OpenAPI 3.1 (API shape), fragment-style, no prose fluff

> **v0.3 change summary.** Six v0.2 claims were disproved by measurement against
> the supplied dataset and are corrected below: batch field names (§4.3),
> `ground_truth` type (§6.4), Completeness vs Recall (§9), plus corrections in
> §2 (no `sport` field; two date fields; bronze ties), §3 (Q2/Q3 too narrow for
> the intent schema; Q5 cannot select a vertex type) and §5 (POST cannot feed
> browser SSE). New: §14 Configuration. Full traceability in `ISSUE-CLOSURE.md`;
> rationale in `DECISION-REGISTER.md`. Where this document and `BUILD-PLAN.md`
> disagree, BUILD-PLAN wins.

---

## 1. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Graph + vector store | TigerGraph Savanna (Community Edition fallback) | 384-dim embeddings fit either |
| Embedding model | all-MiniLM-L6-v2, 384-dim, local via `sentence-transformers`, COSINE similarity | Provider-swappable via config; local = deterministic, zero API cost, no rate limits, removes an external dependency from the reproduce path |
| LLM | **Pluggable — local (Ollama/llama.cpp/vLLM via OpenAI-compatible `base_url`) or free-tier cloud.** One boundary: `common/llm.py`. Pinned within a run, swappable between runs | No LLM in the scoring loop. A capability probe selects native tool-calling or a JSON-schema fallback (§14) |
| Backend | **Python 3.11 · FastAPI · `sse-starlette` · LangGraph/LangChain · pyTigerGraph (async)** | `asyncio.gather` for concurrent invocation. Python is forced: `sentence-transformers` and `pyTigerGraph` are Python-only |
| Frontend | **React + Vite**, native `EventSource` | Independent per-column async rendering + streaming trace |
| Dev acceleration | TigerGraph MCP (optional, SHOULD) | Natural-language GSQL via Cursor/Copilot; 5 MCP tools, one per GSQL query (F-19) |
| Reproduce target | `make reproduce` — single command, clean-clone to full run | Required for reproducibility rubric credit |

## 2. Graph Schema

### 2.1 Vertices

| Vertex | Attributes | Vector |
|---|---|---|
| Document | `doc_id` (= wikidata QID), `title`, `url`, `infobox_type` (**derived from the `[Infobox <type>]` header — not a corpus field**), `approx_tokens`, `wikipedia_pageid` | — |
| OlympicEvent | `event_id`, `event_name`, `competitors` INT, `competitors_text`, `nations` INT, `date_text`, **`date_month`/`date_day_start`/`date_day_end`/`date_year` INT**, `gold`, `silver`, **`bronze` SET\<STRING\>**, `gold_noc`, `win_value`, `win_label`, `parse_confidence` | `emb` (384, COSINE) |
| Games | `games_id` (e.g. `2012-Summer`), `year` INT, `season` | — |
| Sport | `sport_name` | — |
| Venue | `venue_name` | — |
| Chunk | `chunk_id`, `text`, `seq`, `token_count` | `emb` (384, COSINE) |
| Run / Step (SHOULD) | `run_id`/`step_id`, `ordinal`, `method`, `tool`, `tokens`, `ms` | — |

### 2.2 Edges

All endpoints pinned — v0.2 left four undirected, and direction inversion is a named failure mode.

| Edge | From → To | Note |
|---|---|---|
| `DESCRIBES` | Document → OlympicEvent | |
| `AT_GAMES` | OlympicEvent → Games | 21 distinct Games values |
| `IN_SPORT` | OlympicEvent → Sport | 41 sports, derived from title |
| `HELD_AT` | OlympicEvent → Venue | attr `date_text`; 303 venues |
| `PREV_EDITION` / `NEXT_EDITION` | OlympicEvent ↔ OlympicEvent | resolved from infobox `prev`/`next` year fields (93.4% / 97.6% present) |
| `HAS_CHUNK` | Document → Chunk | |
| `RAN_STEP` | Run → Step | cut from Round 1 |

### 2.3 Schema decisions that matter

| Decision | Why |
|---|---|
| `competitors`/`nations` typed INT | `WHERE competitors > 37` becomes a native predicate, not a parse-at-query-time hack — highest-leverage line in the schema |
| `doc_id` = wikidata QID | Retrieval scoring against `gold_doc_ids` is a set comparison, no ID mapping layer |
| `parse_confidence` on OlympicEvent | Partial parses still load; downstream agent sees the gap instead of silently returning a wrong count |
| Person/NOC vertices and `WON_MEDAL` edges | **Cut** — medalists are string attributes on the event; no question type traverses person→events |
| `Sport` derived from the title prefix | **Measured: no infobox carries a `sport` field.** `<Sport> at the <Games>` parses 2,162/2,162 Olympic documents into 41 sports |
| Date parsed into typed INT attributes at ingest | **Measured: two date fields** (`date` 57.9%, `dates` 41.1%), heterogeneous formats, only 81% carry a year. multi_hop + temporal = 50/100 public questions. One normalizer serves ingest and query |
| `bronze` is a set | **Measured: `bronze2`/`bronzeNOC2` on ~13% of events** (third-place ties) |
| `competitors_text` retained | **Measured: 23/2,130 values non-integer** (`23 teams`, `32 (16 pairs)`). Leading integer + `parse_confidence < 1.0`; Q2/Q3 return the excluded count rather than dropping 23 team events |

## 3. GSQL Query Library (exactly five)

Installation takes ~1 minute each and blocks concurrent operations — library stays small and parameterized. Prototype with `INTERPRET QUERY` (no install), install once near the end.

| # | Query | Idiom | Serves |
|---|---|---|---|
| Q1 | `lookup(title \| event_id, target_field)` | Primary-ID hash lookup | lookup |
| Q2 | `count_where(anchor_sport, anchor_games, anchor_venue, constraints_json, field)` | `SumAccum<INT>` in `ACCUM` | aggregation |
| Q3 | `argmax(anchor_sport, anchor_games, anchor_venue, field)` | `HeapAccum<Tuple>(3, field DESC)` | superlative |
| Q4 | `traverse(anchor, edge_type, hops)` | `PREV_EDITION` / `HELD_AT` expansion | temporal, multi_hop |
| Q5 | `hybrid_search(query_vector, k, vtype, candidate_set)` | `vectorSearch({V.emb}, q, k, {candidate_set: vset})` | P1/P2/P3 semantic path |

**Why these are wider than v0.2**: the §7 intent schema emits a four-field
anchor and a *list* of constraints, while v0.2's Q2 took one constraint and no
venue and Q3 took none — any parse with a venue anchor or two constraints had
nowhere to dispatch, and venue disambiguation is a MUST. Both `OlympicEvent`
and `Chunk` carry `emb`, so Q5 must be told which to search; `vtype` keeps the
library at exactly five installed queries.

Vector-index build is asynchronous and lags loading — poll `/restpp/vector/status` for `Ready_for_query` before any benchmark run, or results are silently incomplete.

## 4. API Surface

### 4.1 `POST /query` — interactive single-query comparison

**Request**
```json
{ "query": "string" }
```

**Response** (streamed — see §5)
```json
{
  "query_id": "string",
  "pipelines": {
    "rag": { "status": "running|done|error" },
    "graphrag": { "status": "running|done|error" },
    "agentic_graphrag": { "status": "running|done|error" }
  }
}
```

### 4.2 `GET /query/{query_id}/result`

Returns full record per §6 Data Model, one object per pipeline.

### 4.3 `POST /batch` — headless batch run

**Request**
```json
{
  "questions": [ { "qid": "string", "question": "string", "qtype": "lookup|multi_hop|temporal|aggregation|superlative", "answer": ["string"], "gold_doc_ids": ["string"] } ],
  "run_config": { "llm_provider": "string", "llm_model": "string", "llm_base_url": "string|null", "temperature": 0, "embedding_model": "all-MiniLM-L6-v2", "seed": "string|null", "k": 10, "latency_mode": "throughput|timing", "max_total_tokens": "number" }
}
```
**Corrected in v0.3**: v0.2 specified `question_id`/`text` plus an F-14 adapter
to normalize the hidden set. Measured against the files, **both
`eval_public.jsonl` and `eval_hidden.jsonl` use `qid` / `question` / `qtype`** —
the adapter was unnecessary and would have corrupted the public set. Deleted.
`answer` is a **list** of gold variants, scored max-over-variants.

**Response**
```json
{ "run_id": "string", "record_count": "number", "output_ref": "string" }
```

### 4.4 `GET /batch/{run_id}/records`

Returns array of per-question×pipeline records (§6), for Metrics Dashboard Generator ingestion.

### 4.5 Authentication

All routes except `GET /health` require `X-API-Key`, validated against
`OGR_API_KEY` (§14), enforced as a router-level dependency so a new endpoint is
protected by default rather than by being remembered.

Browser `EventSource` cannot send custom headers, so SSE routes use a
**short-lived, single-use stream token** returned with the id from `POST /query`
and `POST /build`, passed as `?token=`. The long-lived key never enters a URL,
browser history or an access log.

### 4.6 `POST /build` · `GET /build/{build_id}/stream`

Starts ingestion and streams `BuildEvent`
`{stage, pipeline_affected[], status, items_done, items_total, elapsed_ms, tokens, note}`.
`tokens` is **0** for every ingestion stage — parsing is deterministic and the
embedding model is local, so no LLM runs in this path.

## 5. Streaming Protocol (Agentic Trace)

Decision: **SSE**, one event per trace step, event payload = single trace record (§6.3). Revisit only if cancel/interrupt becomes a requirement (would need WebSocket).

**Corrected in v0.3**: §4.1 described a streamed response to `POST /query`, but
browser `EventSource` is GET-only. `POST /query` returns
`202 {query_id, stream_token}`; the stream is `GET /query/{query_id}/stream?token=…`.

## 6. Data Model

### 6.1 Query-level record

```json
{
  "query_id": "string",
  "query_text": "string",
  "qtype": "lookup|multi_hop|temporal|aggregation|superlative",
  "timestamp": "ISO8601",
  "pipelines": { "rag": "PipelineRecord", "graphrag": "PipelineRecord", "agentic_graphrag": "PipelineRecord" },
  "verdict": {
    "token_multiplier_vs_rag": "number",
    "token_multiplier_vs_graphrag": "number",
    "accuracy_delta_vs_rag": "number|\"n/a\"",
    "accuracy_delta_vs_graphrag": "number|\"n/a\"",
    "summary_line": "string"
  }
}
```

### 6.2 PipelineRecord

```json
{
  "pipeline": "rag|graphrag|agentic_graphrag",
  "answer": "string (short span — this is what EM/F1 score)",
  "explanation": "string (prose with citations — displayed, never scored)",
  "citations": [ { "source_id": "string (parent doc_id = wikidata QID — scored)", "chunk_id": "string|null (displayed)", "ref_type": "chunk|entity|relationship" } ],
  "chunks_returned": "number",
  "citations_count": "number",
  "tokens": { "input": "number", "output": "number", "total": "number" },
  "token_source": "provider|local_tokenizer",
  "latency_ms": "number",
  "trace": "TraceStep[] | null",
  "strategy_changed": "boolean | null",
  "stop_reason": "string | null",
  "status": "done|error",
  "error_detail": "string | null"
}
```

### 6.3 TraceStep (agentic_graphrag only)

```json
{
  "step_n": "number",
  "agent_type": "entity_linking|graph_traversal|similarity_search|document_retrieval|aggregation|multi_hop_reasoning|evidence_evaluation",
  "tool_called": "string (Q1-Q5 or agent name)",
  "tokens": { "input": "number", "output": "number" },
  "chunks_returned": "number",
  "citations_count": "number",
  "latency_ms": "number",
  "strategy_change": "boolean",
  "notes": "string"
}
```

### 6.4 Batch record

```json
{
  "run_id": "string",
  "question_id": "string",
  "question_text": "string",
  "qtype": "string",
  "ground_truth": ["string"],
  "gold_doc_ids": ["string"],
  "record": "QueryLevelRecord (§6.1)"
}
```

## 7. Intent Schema (P3 only)

Emitted by the Intent Parser via LLM function-calling, schema-validated with one retry on failure. No question-template regex anywhere in this path.

```json
{
  "operation": "LOOKUP | COUNT | ARGMAX | TRAVERSE",
  "anchor": { "sport": "string|null", "games": "string|null", "venue": "string|null", "title": "string|null" },
  "constraints": [ { "field": "string", "op": ">|<|=|>=|<=", "value": "number|string" } ],
  "target_field": "gold | nations | event_name | ..."
}
```

**Definition of "fully-specified anchor"** (v0.2 used the term without defining
it, which made FR-11 untestable): fully-specified ⇔ (`anchor.title` or
`anchor.event_id` non-null) **and** `target_field` non-null **and**
`constraints` empty. Everything else is underspecified and routes to the loop.

**qtype → operation**: lookup→LOOKUP · aggregation→COUNT · superlative→ARGMAX ·
temporal and multi_hop→TRAVERSE. `qtype` is an **eval-set label and is never
read at runtime** — reading it would be training on the test set and would
violate NFR-7. The mapping exists for reporting only.

Dispatch is `operation → query` per §3. This is executable semantic parsing to a fixed operation vocabulary, not text-to-GSQL generation (which has well-documented failure modes: schema misunderstanding, relationship-direction inversion, right-query-wrong-answer).

## 8. Pipeline Contracts

### 8.1 P1 — RAG Pipeline

| Step | Detail |
|---|---|
| Retrieval | Q5 vector top-k only. **No type filtering** — deliberate, its ceiling must be visible, not masked |
| Generation | Single LLM call with retrieved chunks as context |
| Output | answer, chunk citations, tokens, latency |

### 8.2 P2 — GraphRAG Pipeline

| Step | Detail |
|---|---|
| Retrieval | **Same intent parser as P3**, then exactly one query — no evidence check, no fallback, no loop |
| Generation | Single LLM call with graph context |
| Output | answer, entity/relationship citations, tokens, latency |

**Corrected in v0.3**: v0.2 routed P2 by a "static rule table" keyed on question
type. That is not implementable — `qtype` is an eval-set label and NFR-7 forbids
question-template regex in the answer path, so the specified routing must either
read the test label or pattern-match the question. Sharing P3's parser also
makes the three-way comparison a clean ablation: **P1 removes the graph, P2
removes the loop, P3 has both.**

### 8.3 P3 — Agentic GraphRAG Orchestrator

| Step | Detail |
|---|---|
| Intent parse | §7 schema via function-calling |
| Necessity routing | Per ARCHITECTURE-SPEC §5 — LOOKUP direct, COUNT/ARGMAX one scoped query, TRAVERSE/underspecified → loop |
| Loop (when routed) | Tool Router → Specialised Agent → Evidence Evaluator → repeat until Stopping-Criteria Evaluator signals done |
| Output | answer, citations, full trace, `strategy_changed`, `stop_reason`, cumulative tokens/latency |

## 9. Evaluation

| Metric | Definition |
|---|---|
| Exact match (EM) | SQuAD-style normalization: lowercase, strip punctuation and articles, collapse whitespace; max over gold variants |
| Token F1 | Same normalization, token overlap |
| Recall@k / Precision@k | Retrieved doc set vs `gold_doc_ids` |
| Completeness | **An explicit alias of Recall**, retained because the guidebook names it. Corrected in v0.3: `\|retrieved ∩ gold\| / \|gold\|` *is* recall, so v0.2 reported one quantity in two columns |
| Precision / Recall / F1 | Over the **returned document set**, for all three pipelines. Corrected in v0.3: `@k` is undefined for P2 and P3, which retrieve by traversal. `k = 10` applies to P1 only and is fixed before the first run, never tuned against results |
| Tokens / latency | Provider-reported usage only, one accounting module, prompt and completion tracked separately |
| Per-qtype breakdown | Every metric above, split by lookup/multi_hop/temporal/aggregation/superlative — this is the headline artifact |

**Answer contract (new in v0.3, and load-bearing):** every pipeline returns
`{"answer": "<shortest span answering the question>", "explanation": "<prose
with citations>"}` from a prompt byte-identical across P1/P2/P3 apart from
retrieved context. EM and token F1 score `answer` only. Without this, a correct
answer phrased as a sentence scores EM = 0 for all three pipelines and the
comparison is flat — the benchmark cannot register a correct answer.

**Multi-person answer rule:** 2/100 public answers contain concatenated names
(pub-015, pub-099). Split on lowercase→uppercase boundaries into a name set,
score as set overlap — **with a prefix guard** for `Mc`, `Mac`, `O'`, `Di`,
`De`, `Van`, `Le`, `La`. Corrected in v0.3: the unguarded rule mis-splits
`Rosannagh MacLennan` (pub-067). Note the corpus concatenates `gold` the same
way, so the guard is needed at ingest too.

No LLM sits in the scoring loop — deterministic and reproducible run-to-run; this is the Investigation-accuracy (30%) and Evidence-quality (15%) evidence base.

## 10. Metrics Dashboard — Required Aggregations

| Chart/Table | Source fields |
|---|---|
| Per-qtype matrix (EM, F1, Recall, Precision, Completeness × 5 qtypes × 3 pipelines) | §9 metrics, `qtype` |
| Accuracy-vs-tokens scatter | `tokens.total` (x) vs EM/F1 (y), per pipeline |
| Agentic step-count distribution | `trace.length` across agentic runs |
| Strategy-change frequency | count of `strategy_change: true` across agentic runs |
| Stop-reason breakdown | frequency by `stop_reason` value |
| Trace viewer (drill-down) | full `TraceStep[]` for a selected query |

## 11. Non-Functional Implementation Notes

| Concern | Implementation note |
|---|---|
| Concurrency | Dispatcher fires all 3 pipeline calls via `asyncio.gather`, not sequential await |
| Latency comparability | 3 concurrent pipelines × a batch pool of 6 is up to 18 in-flight provider calls, and queuing inflates `latency_ms` unevenly. Two run modes: `--throughput` (pool 6) for accuracy and token metrics, which are pool-invariant, and `--timing` (pool 1) for the latency figures shown in the dashboard. The run header records which |
| Fault isolation | Each pipeline call wrapped in try/catch at Dispatcher level; partial failure → other 2 records still returned |
| Instrumentation | Token/latency capture wraps every LLM and retrieval call at the lowest invocation point, not estimated post-hoc. Σ `TraceStep.tokens` is **asserted** equal to the record total. Where the configured provider reports no usage — common for local servers — the model's tokenizer is used and `token_source` is set to `local_tokenizer` so the figure is labelled rather than silently zero |
| Reproducibility | `run_config` (model, embedding_model, seed) persisted alongside every batch record; local embedding removes provider-drift risk |
| GSQL install cost | Prototype via `INTERPRET QUERY`; install all 5 once, near the end of the build window (each install ~1 min, blocks concurrent ops) |
| Vector readiness gate | Poll `/restpp/vector/status` for `Ready_for_query` before any benchmark run — a `/vector/status` UI/CLI gate should block eval start otherwise |

## 12. Deployment

| Item | Status |
|---|---|
| `run.sh` / Dockerfile | Not yet defined — required for reproducibility, add before submission |
| `make reproduce` | Required target — clean-clone to full run, no manual steps |
| Environment config | TigerGraph Savanna connection string, LLM API key via env vars (no API key needed for embeddings — local model) |
| Corpus ingestion script | Infobox parser + normalizer (INT casting) with a coverage report; fail loudly on unparseable `competitors` rather than defaulting |
| Attribution | Corpus is CC BY-SA 4.0 — attribution required in repo/submission |

## 13. Technical Decisions — all closed

No open technical decisions remain. Full rationale and rejected alternatives in
`DECISION-REGISTER.md`; closure traceability in `ISSUE-CLOSURE.md`.

| Decision | Status |
|---|---|
| Backend framework | **Closed** — Python 3.11 + FastAPI + `sse-starlette` |
| Frontend framework | **Closed** — React + Vite |
| Streaming transport | **Closed** — SSE; `POST → 202`, `GET …/stream?token=` |
| Ground-truth scoring | **Closed** — deterministic EM/F1, no LLM judge |
| Embedding model | **Closed** — all-MiniLM-L6-v2, 384-dim, local encoder; **vectors stored in TigerGraph** |
| LLM provider | **Closed** — pluggable (local or free cloud), one boundary, pinned per run |
| Batch output storage | **Closed** — append-only JSONL per run, `run_config` header |
| Trace-as-graph write-back | **Cut from Round 1** |
| P2 routing | **Closed** — reuses P3's intent parser, single query, no loop |
| Answer contract | **Closed** — shared `{answer, explanation}`, EM/F1 score `answer` |
| Latency measurement | **Closed** — `--throughput` / `--timing` run modes |

## 14. Configuration (new in v0.3)

Structure follows `tigergraph/graphrag`'s `server_config.json` — `db_config` /
`llm_config` / service sections — so it is recognisable to anyone who knows the
reference implementation. Two differences, both deliberate: **no secret is ever
written to a config file** (secrets come from the environment and the file
carries only their variable names), and `run_config` is persisted with every
batch record because it is part of the run's identity.

### 14.1 `config/server_config.json` (committed, no secrets)

```json
{
  "db_config": {
    "hostname": "${TG_HOST}",
    "graphname": "OlympicGraphRAG",
    "restppPort": "14240",
    "gsPort": "14240",
    "default_timeout": 300,
    "default_mem_threshold": 5000,
    "default_thread_limit": 8,
    "useCert": true,
    "certPath": null
  },
  "llm_config": {
    "completion_service": {
      "llm_service": "${LLM_PROVIDER}",
      "llm_model": "${LLM_MODEL}",
      "base_url": "${LLM_BASE_URL}",
      "model_kwargs": { "temperature": 0, "max_tokens": 1024 },
      "supports_tool_calling": "auto",
      "reports_token_usage": "auto"
    },
    "embedding_service": {
      "embedding_model_service": "local",
      "model_name": "sentence-transformers/all-MiniLM-L6-v2",
      "dimension": 384,
      "similarity": "COSINE"
    },
    "rate_limit": { "max_concurrent": 2, "requests_per_minute": 30, "backoff_base_s": 2, "max_retries": 5 }
  },
  "api_config": {
    "host": "127.0.0.1",
    "port": 8000,
    "stream_token_ttl_s": 300
  },
  "run_defaults": {
    "k": 10,
    "chunk_tokens": 300,
    "chunk_overlap": 50,
    "max_steps": 6,
    "max_tokens_per_query": 20000,
    "max_total_tokens": 5000000,
    "latency_mode": "throughput",
    "parse_confidence_threshold": 0.9
  }
}
```

`supports_tool_calling` and `reports_token_usage` accept `auto` (probe at
startup), `true` or `false`. `auto` is the default because the whole point of a
pluggable LLM is that these differ by provider — an assumption here is what
breaks P3 silently on a local model.

### 14.2 `.env.example` (committed) — secrets live only here

```bash
# ── TigerGraph ────────────────────────────────────────────────
TG_HOST=https://<workspace>.i.tgcloud.io   # Savanna workspace, or http://localhost for CE
TG_USERNAME=tigergraph
TG_PASSWORD=
TG_SECRET=                                  # Savanna: secret used to mint a token
TG_TOKEN=                                   # optional: pre-minted REST++ token
TG_GRAPHNAME=OlympicGraphRAG

# ── LLM (pluggable: local or free-tier cloud) ─────────────────
LLM_PROVIDER=openai_compatible              # openai_compatible | openai | google_genai | groq | ollama
LLM_MODEL=qwen2.5:7b-instruct
LLM_BASE_URL=http://localhost:11434/v1      # local server; leave blank for a hosted provider
LLM_API_KEY=                                # blank for a local server that needs none

# ── This application's own API ────────────────────────────────
OGR_API_KEY=                                # X-API-Key required on every route except /health
OGR_HOST=127.0.0.1
OGR_PORT=8000

# ── Frontend (build-time) ─────────────────────────────────────
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_KEY=                               # see the note below
```

### 14.3 Rules

| Rule | Reason |
|---|---|
| `.env` is git-ignored; `.env.example` is committed with empty values | The shape is documentation; the values are secrets |
| No credential appears in `server_config.json`, in a persisted record, in an SSE frame or in a log | Enforced by a write-time assertion in the record store, not by reviewer attention |
| `run_config` — provider, model, base URL, temperature, seed, `k`, chunking, budgets, latency mode — is written into every run's header | A result without its run conditions is not reproducible (NFR-4) |
| The model is pinned within a run and swappable between runs | Pluggability is a portability property, not a benchmarking one. A run whose model changed midway measures a model difference dressed as an architecture difference |
| `VITE_API_KEY` is shipped to the browser and is therefore **not a secret** | It protects against casual access on a shared network, which is the real threat here. Defence in depth is the `127.0.0.1` default binding. Do not reuse this key anywhere that matters |
| Switching to a hosted provider means editing `.env` and rerunning — no code change | Single boundary: `common/llm.py`. Nothing else constructs a model client |
