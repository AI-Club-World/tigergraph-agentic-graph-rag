# tigergraph-agentic-graph-rag

Three pipelines — RAG, GraphRAG and Agentic GraphRAG — answer the same
questions over the same corpus, side by side. The benchmark shows when a
multi-step agentic investigation beats simpler retrieval, and when it is
overkill once tokens, latency and complexity are counted.

The repo holds two modules:

- `backend/`: the FastAPI service, the three pipelines, ingestion, the GSQL
  schema and query library, the deterministic scorer/dispatcher/aggregator, the
  batch runner and the CLI.
- `frontend/`: the React UI, with Search, Build, Dashboard and History screens
  and a Settings panel.

## Documentation

| Document | What it is |
|---|---|
| [`config-docs/APPLICATION-SPEC.md`](config-docs/APPLICATION-SPEC.md) | Functional and non-functional requirements (FR/NFR) |
| [`config-docs/ARCHITECTURE-SPEC.md`](config-docs/ARCHITECTURE-SPEC.md) | Architecture diagram, the agents, routing, decision log, engineering guards, where the LLM is used, known limitations |
| [`config-docs/TECHNICAL-SPEC.md`](config-docs/TECHNICAL-SPEC.md) | Stack, graph schema, query library, record contracts, evaluation |
| [`config-docs/UI-SPEC.md`](config-docs/UI-SPEC.md) | Frontend contract: screens, states, data, formatting |
| [`config-docs/EMBEDDING-SWITCHING.md`](config-docs/EMBEDDING-SWITCHING.md) | Selectable embedding models, per-model storage, the switch/re-embed jobs |
| [`config-docs/WRITEUP.md`](config-docs/WRITEUP.md) | Submission write-up: what was built, measured results, limitations, next steps, demo script |
| [`config-docs/SCORE-AUDIT.md`](config-docs/SCORE-AUDIT.md) | Rubric audit: baseline, root causes, owner decisions, before/after scores |
| [`submission/`](submission/README.md) | Hidden-set raw outputs (answers, tokens, citations, agentic traces) and the public and hidden run reports |
| [`config-docs/DEPLOY.md`](config-docs/DEPLOY.md) | Hosting the frontend on Netlify |
| [`data/README.md`](data/README.md) | The corpus and question sets, and how dataset names are resolved |
| [`ATTRIBUTION.md`](ATTRIBUTION.md) | Licences for the corpus, embedding models and software |

## Getting started

Two pieces run here: the **backend** (FastAPI, the three pipelines and
TigerGraph) and the **frontend** (the React UI). For real answers, run both at
once in two terminals, pointed at each other. The frontend can also run alone
on fixture data (mock mode). Mock mode is **off** by default. See
[Mock mode](#mock-mode).

On Windows, `run.bat` opens both dev servers in separate windows. It uses
`backend/run-backend.bat`, which expects a virtual environment at
`backend/.venv`, and `frontend/run-frontend.bat`.

### Prerequisites

| Needed | Version | Why |
|---|---|---|
| Python | 3.11+ | Backend |
| Node.js | 20+ | Frontend (Vite, React) |
| A TigerGraph workspace | Savanna (cloud) or Community Edition 4.2+ | Vectors *and* the graph both live there. There is no FAISS/Chroma/pgvector substitute |
| An LLM endpoint | Gemini, Groq, NVIDIA NIM, Anthropic, OpenAI, or any OpenAI-compatible server (Ollama, llama.cpp, vLLM) | Intent parsing, answer generation, groundedness checks |
| An embedding backend | Cloudflare Workers AI credentials, or local `sentence-transformers` | Chunk and query embeddings |

### 1. Configure the backend

From the repo root:

```bash
cp env.example .env
```

Settings are read in this order: the environment (`.env`) first, then
`config/server_config.json` (committed, contains no secrets), then the code
default. The main variables:

| Variable(s) | What to put there |
|---|---|
| `TG_HOST` | Your workspace endpoint, the full `https://…` URL (Savanna: workspace page → **Connect**) |
| `TG_TOKEN`, or `TG_USERNAME`/`TG_PASSWORD`, or `TG_SECRET`, or `TG_JWT_TOKEN` | Whichever credential style your workspace issues. See the comment above `_connect()` in `backend/src/ogr/graph/client.py` if you set more than one |
| `TG_CLOUD` | `true` for Savanna. It changes how pyTigerGraph builds URLs and negotiates auth |
| `TG_GRAPHNAME` | Defaults to `OlympicGraphRAG` |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_BASE_URL` | The startup LLM. `LLM_PROVIDER` is `anthropic`, `google`, `openai` or `openai_compatible`. For `openai_compatible` (Groq, Ollama, …), set `LLM_BASE_URL` too. Code default: `openai_compatible`, `qwen2.5:7b-instruct` at `http://localhost:11434/v1` (Ollama) |
| `GEMINI_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY` | Keys for the three providers you can pick at runtime in the Settings panel. Leave a provider's key empty and that provider is disabled in the panel. The chosen model applies to all three pipelines |
| `EMBEDDING_MODEL` | The startup embedding model, by key (table below). Default `bge-large-en-v1.5`. After the first switch in Settings, the active model is stored in `out/embeddings.json` and overrides this value |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Workers AI. They serve `bge-large-en-v1.5` embeddings and the Agentic pipeline's reranker (`@cf/baai/bge-reranker-base`). Without them, or when a call fails, both run the same models locally (`sentence-transformers`) |
| `EMBEDDING_HOST_URL` | Optional self-hosted embedding service serving the catalog models: `POST {url}/embed` with `{"model": "<key>", "texts": [...]}` returns `{"embeddings": [...]}`. Tried first; on failure the next tier runs |
| `EMBEDDING_CLOUDFLARE`, `EMBEDDING_REMOTE` | `false` skips the Cloudflare embedding tier (e.g. quota spent), or every remote tier. Both default to `true` |
| `OGR_API_KEY` | Required. Every authenticated route returns `503` until it is set. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `OGR_ADMIN_KEY`, `OGR_SESSION_TTL_S` | Optional admin key: set, `OGR_API_KEY` becomes a viewer key and only this key can build, upload, switch embeddings, change settings or start benchmarks. Session lifetime after sign-in (8 h) |
| `OGR_CORS_ORIGINS` | Browser origins allowed to call the API. Defaults to `http://localhost:5173,http://127.0.0.1:5173`, the Vite dev server |
| `RUN_K`, `RUN_CHUNK_TOKENS`, `RUN_CHUNK_OVERLAP` | Retrieval and chunking (10 / 300 / 50). They are fixed before the first run and never tuned against results |
| `RUN_MAX_STEPS`, `RUN_MAX_TOKENS_PER_QUERY`, `RUN_MAX_TOTAL_TOKENS` | Agentic loop limit (6), per-query token budget (20,000) and whole-run token ceiling (5,000,000; `0` turns it off) |
| `RUN_POOL_SIZE`, `RUN_LATENCY_MODE`, `LLM_REQUESTS_PER_MINUTE` | Batch concurrency (2), `throughput` or `timing`, and the client-side rate limit (30 in `server_config.json`; `0` turns it off) |
| `HEALTH_LLM_TIMEOUT_S` | How long `/health/llm` waits for its one-token completion (120 s) |

The five selectable embedding models (`backend/src/ogr/common/embedding_models.py`).
The graph stores embeddings for at most two of them at once.

| `EMBEDDING_MODEL` key | Hugging Face id | Dim | Served by |
|---|---|---|---|
| `qwen3-embedding-0.6b` | `Qwen/Qwen3-Embedding-0.6B` | 1024 | local |
| `embeddinggemma-300m` | `google/embeddinggemma-300m` | 768 | local |
| `gte-large-en-v1.5` | `Alibaba-NLP/gte-large-en-v1.5` | 1024 | local |
| `mxbai-embed-large-v1` | `mixedbread-ai/mxbai-embed-large-v1` | 1024 | local |
| `bge-large-en-v1.5` (default) | `BAAI/bge-large-en-v1.5` | 1024 | Cloudflare when configured, else local |

Every model is tried in the order: `EMBEDDING_HOST_URL`, then Cloudflare (for the
model it hosts), then local. All tiers produce the same vectors for a model, so
a build and its queries may use different tiers.

`.env` is git-ignored. Never commit real values, and never put a secret in a
`VITE_`-prefixed variable: those values are compiled into the browser bundle.

### 2. Install, verify and build

```bash
pip install -e "backend[dev]"
python -m ogr.cli verify --pre-build   # LLM, embedding and TigerGraph reachable; missing queries are a warning
python -m ogr.cli build                # chunk + embed, install schema, load graph, install Q1–Q5
```

`verify` spends only a few tokens and changes nothing. Without `--pre-build`,
missing GSQL queries (`q1_lookup` … `q5_hybrid_search`) count as a failure.

`build` **resets the graph**. It reinstalls the schema, so every dataset that
was loaded before is removed. It then loads `data/corpus/corpus.jsonl` (change
this with `--corpus`) with the active embedding model. It waits for the vector
index to report `Ready_for_query` (`--vector-timeout`, default 600 s). To add
datasets alongside the ones already loaded, use the Build screen instead
(`POST /build`).

### 3. Start the API

```bash
python -m uvicorn ogr.api.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

Check it: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`.

### 4. Start the frontend

```bash
cd frontend
npm install
cp .env.example .env    # no key here: the UI asks for it at sign-in
npm run dev
```

Open **http://localhost:5173**. The defaults already point at
`http://127.0.0.1:8000` with mock mode off.

### Reproduce everything

With `.env` filled in, `make reproduce` runs these steps in order:

1. `install`: `pip install -e backend[dev]` and `npm ci`.
2. `check`: ruff, pytest, eslint, the frontend build and vitest.
3. `verify`: runs `verify --pre-build`.
4. `build`: rebuilds the graph.
5. `benchmark` and `timing`: run `data/questions/eval_public.jsonl` in `throughput` and `timing` mode.
6. `holdout`: runs `acceptance/holdout/eval_hidden.jsonl`.
7. `results`: writes `out/<RUN_ID>-public-report.md` (the run report below) and
   `out/<RUN_ID>-holdout-export.json` (the hidden-set submission).

`make smoke` asks one question through all three pipelines against the live
graph. It is the quickest check that the GSQL queries and the LLM work end to end.

Every step shares one `RUN_ID`. Outputs go to `out/<RUN_ID>-public.jsonl`,
`-public-timing.jsonl` and `-holdout.jsonl`, plus the two results files.

## Security model

No secret ships in the browser bundle. The UI asks for an access key at
**sign-in** and exchanges it (`POST /auth/session`) for a random session
token. The token is held server-side with an expiry (`OGR_SESSION_TTL_S`,
8 h), is revocable (Sign out), and lives in the browser tab's
`sessionStorage` only. The frontend build refuses to run with a
`VITE_API_KEY` set, so an old `.env` cannot leak a key into the JavaScript.

Two keys, two roles:

| Key | Role | Can |
|---|---|---|
| `OGR_API_KEY` | viewer (admin when no admin key is set) | ask questions, read runs, history and settings |
| `OGR_ADMIN_KEY` (optional) | admin | also build or reset the graph, upload datasets, switch or evict embedding models, change the LLM, start benchmarks, import runs |

Give judges or reviewers the viewer key; keep the admin key to yourself. Ten
wrong keys from one client in ten minutes lock it out for the rest of the
window. Scripts and the CLI may send a key directly as `X-API-Key`.

Still run the backend behind HTTPS in any public deployment (the key is sent
once, at sign-in), and never reuse a key that protects anything else. Backend secrets (`TG_*`, `LLM_API_KEY`, provider keys,
`CLOUDFLARE_API_TOKEN`) stay in the backend `.env`. They never go in the
frontend.

# Backend

## CLI (`python -m ogr.cli`)

| Command | What it does |
|---|---|
| `verify [--pre-build]` | Checks the LLM, the embedding backend and TigerGraph, and whether Q1–Q5 are installed. Exit code 0 only when nothing fails |
| `build [--corpus PATH] [--vector-timeout S]` | Full reset and load of one corpus, as described above |
| `batch QUESTIONS.jsonl --out OUT.jsonl [--run-id ID] [--mode throughput\|timing] [--embedding-model KEY]` | Runs a question set through all three pipelines and appends one scored record per question (details below) |
| `ask "<question>" [--pipelines rag,graphrag,agentic_graphrag] [--embedding-model KEY] [--json] [--show-trace]` | Answers one question from the terminal. Default pipeline: `rag`. Aliases: `graph`, `agentic` |
| `coverage [--corpus PATH] [--out out/ingest-coverage.md]` | Parses the corpus infoboxes and writes the ingest coverage report |
| `report RUN.jsonl [--out REPORT.md]` | Markdown run report: EM/F1/completeness/grounding and token cost per pipeline; per question type the Agentic − RAG gap, token ratio and a worth-it verdict; necessity routing (direct vs loop, with a labelled token-savings estimate); agents, tools and stop reasons |
| `export RUN.jsonl --out EXPORT.json` | Submission JSON: per question and pipeline the answer, explanation, tokens, latency, citations (with evidence snippets) and, for Agentic, the full trace |

How `batch` behaves:

- **Run id.** Defaults to a UTC timestamp. The mode defaults to `RUN_LATENCY_MODE`. `timing` runs with a pool size of 1, so its latencies are comparable.
- **Resume.** Rerunning the same command against an existing `--out` file skips every question already recorded successfully. A question whose latest record has a pipeline error is retried, and the new record supersedes the old one.
- **Stops and exit codes.** A rate-limit error stops the run: no new question starts. If any question was not recorded, or the `RUN_MAX_TOTAL_TOKENS` ceiling was reached, the command exits 1 with the reason. The ceiling counts tokens across resumes. Rerun to continue.

Tests and lint: `cd backend && pytest -q` and `cd backend && ruff check src tests`.

## HTTP API

Routes from `backend/src/ogr/api/main.py`. **Auth** is a session
(`Authorization: Bearer <token>` from `POST /auth/session {key}`) or the key
itself as `X-API-Key`, unless stated otherwise; routes that change state need
the admin role (`OGR_ADMIN_KEY`, or `OGR_API_KEY` when no admin key is set)
and answer `403` to a viewer. An unset `OGR_API_KEY` returns `503` on every key-protected
route. A wrong or missing key returns `401`. The two SSE streams take the
single-use `stream_token` from the start response as `?token=`, because
browser `EventSource` cannot send headers.

| Method and path | Auth | Purpose |
|---|---|---|
| `GET /health` | none | Liveness: `{"status":"ok"}` |
| `GET /health/db`, `/health/llm`, `/health/embedding` | none | One dependency check each. Results are cached for 30 s, and hosts are redacted |
| `GET /settings` | none | Effective LLM provider/model and embedding model (no secrets) |
| `GET /settings/providers` | key | Gemini / NVIDIA NIM / Groq presets and whether each key is set |
| `GET /settings/models?provider=` | key | That provider's live model list. NVIDIA is narrowed to free endpoints |
| `PATCH /settings` | key | Change the provider/model at runtime. Also switches the embedding model when the target is already complete |
| `GET /embeddings` | key | Each embedding model's state, the 2-model cap and the current job |
| `GET /embeddings/plan?model=` | key | What switching to `model` would do |
| `POST /embeddings/switch` | key | Switch the embedding model. `mode` is `replace` or `parallel`. At the cap, `evict` names the model to delete |
| `POST /embeddings/resume` | key | Continue a failed re-embed job from its last batch |
| `POST /embeddings/{model}/complete` | key | Embed the chunks a stored model is missing |
| `POST /query` | key | `{query, embedding_model?}` → `202 {query_id, stream_token}`. Returns `409 embedding_mismatch` when the model has no complete embeddings |
| `GET /query/{id}/stream?token=` | stream token | SSE: `trace`, `pipeline`, `done` |
| `GET /query/{id}/result` | key | The merged `QueryLevelRecord`. Returns `409` while the query is still running |
| `GET /corpora` | key | Datasets in `data/corpus/` with display names, and which are loaded |
| `POST /corpora/{name}` | key | Upload a JSONL dataset (the request body is the file). Options: `unique`, `overwrite`, `title`, `source_file` |
| `PATCH /corpora/{name}` | key | Rename a dataset (`title`, `description`) |
| `POST /build` | key | `{dataset, rebuild, reset}` → `202 {build_id, stream_token}`. Returns `409` with `already_built`, `reset_required`, `build_running`, `embedding_job_running`, `batch_running` or `embedding_cap` |
| `GET /build/current` | key | The latest build and its events, so a reloaded page can resume following it |
| `GET /build/{id}/stream?token=` | stream token | SSE: `build`, `done` |
| `GET /datasets` | key | Question sets in `data/questions/` |
| `POST /batch` | key | `{dataset, run_id?, latency_mode?, resume?}` → `202 {run_id, status}`. Records go to `out/{run_id}.jsonl` |
| `GET /runs` | key | One summary per stored run, newest first |
| `POST /runs/import` | key | Import a run export, a record list or a native JSONL file. Returns `409` if the run id already exists |
| `GET /batch/{run_id}/records` | key | A run's scored records |
| `GET /history?kind=&limit=` | key | Every query, build, benchmark and embedding-job attempt (`out/history.jsonl`), newest first |

State is kept in process memory (one uvicorn worker). A restart loses
in-flight queries and builds. Runs, history, the dataset registry and the
embedding store are files under `out/`.

## Design notes

How the pipelines differ, where the LLM is called, and the known limitations
of the comparison are in `config-docs/ARCHITECTURE-SPEC.md`. Two facts that
matter when reading results:

- No LLM sits in the scoring path. EM and token F1 are computed
  deterministically against the gold answers.
- P1 (RAG) is deliberately unfiltered: one k=10 vector search with no
  reranking or type filter. The Agentic pipeline can make several retrieval
  attempts, so part of any lift over P1 comes from *more attempts*, not only
  *smarter retrieval*.

# Frontend

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server on :5173 |
| `npm run build` | Type-check (`tsc --noEmit`), then a production build into `frontend/dist` |
| `npm run preview` | Serve the production build |
| `npm run lint` | ESLint |
| `npm test` | Vitest (jsdom) |

## Screens

| Route | Screen |
|---|---|
| `/` | **Search**. One question, three result columns that settle independently, the live agentic trace and the verdict strip. **Stop waiting** stops following a slow run. If the embedding model has no complete embeddings, a popup offers the models that do |
| `/build` | **Build**. Pick, upload or rename a dataset (JSONL in `data/corpus/`) and build it into the shared graph next to datasets already loaded. Building a loaded dataset asks Rebuild or Cancel. Readiness is shown per pipeline, and a failure notice gives the reason |
| `/dashboard` | **Dashboard**, with three tabs (`?tab=dashboard\|runs\|eval`). **Dashboard**: aggregates over one run, including a cost/latency/reliability table and the agents-invoked table. **Run benchmark**: start a run; history, import/export and comparison. **Eval table**: every question × three pipelines, with drill-down |
| `/history` | **History**. Every query, build, benchmark and embedding-job attempt, with type/status filters and search |
| `/benchmarks`, `/eval` | Redirect to the Run benchmark and Eval table tabs (keeping `?run=`) |

The header shows health indicators for TigerGraph, the LLM and the embedding
backend. Features whose service is down are blocked, with a contact link
(`VITE_ADMIN_EMAIL`). The **Settings** panel (gear icon) sets:

- the LLM provider (Gemini, NVIDIA NIM or Groq) and model, with a filter over
  the provider's live model list and a custom model id field;
- the embedding model, through a decision dialog (re-embed or keep parallel
  indices; eviction at the 2-model cap). See
  `config-docs/EMBEDDING-SWITCHING.md`.

The panel closes itself 10 s after a successful Apply. Settings are hidden in
mock mode.

On the Dashboard tabs, `?run=` selects a run. Without it, a live backend opens
its newest run.

## Mock mode

Mock mode is off unless `VITE_USE_MOCK_API=true`. Any other value, including
empty, uses the live backend. In mock mode:

- every screen replays fixtures from `src/fixtures/`, which are illustrative
  and not measured;
- a `mock data` chip shows in the header;
- runs `latest` (20 scored questions) and `hidden` (8, no gold) are available;
- the Settings panel, uploads and History need the live backend.

`VITE_MOCK_LATENCY_SCALE=0` makes the replay instant.

## Folder structure

```
frontend/
  .env.example            every build-time variable
  public/_redirects       SPA rewrite for folder deploys
  src/
    config.ts             the single config point (base URL, API key, mock switch, polling)
    types.ts              record contracts: PipelineRecord, TraceStep, BatchRecord, RunSummary, …
    format.ts             number/duration formatting, mean, median
    main.tsx  App.tsx     router shell, header, redirects
    SearchView.tsx        Search screen
    TracePanel.tsx        agentic trace (also used in the eval drill-down)
    BuildView.tsx         Build screen: dataset picker/upload/rename, per-pipeline progress
    DashboardPage.tsx     Dashboard tabs
    Dashboard.tsx         aggregate view over one run
    BenchmarksView.tsx    Run benchmark tab: run, history, import/export, compare
    EvalTable.tsx         per-question table with drill-down
    HistoryView.tsx       History screen
    SettingsPanel.tsx     provider/model settings
    ServiceStatus.tsx  useServiceStatus.ts   health indicators, RequiresServices gate
    useBatchRecords.ts    loads the ?run= run (newest when absent, live)
    useTheme.ts           light/dark toggle (localStorage key ogr-theme)
    components/           QueryInput, ResultColumn, VerdictStrip, CitationList, StatusBadge,
                          RunPicker, Charts, colors, Icon, Notice, ErrorBoundary,
                          EmbeddingSettings, EmbeddingMismatchDialog, useDialogFocus
    services/
      http.ts             fetch wrapper (session Bearer token, ApiError) + EventSource helper
      session.ts          sign-in / sign-out, the session token (sessionStorage)
      queryService.ts  buildService.ts  batchService.ts  benchmarkService.ts
      datasetService.ts  historyService.ts  settingsService.ts
      mock/               transport.ts (fixture replay), runs.ts (mock run history)
    fixtures/             JSON shaped to the API contracts
    test/setup.ts
```

Components never touch fixtures. They call `services/*Service.ts`, and each
service branches on `config.useMockApi`.

## Light and dark mode

The header toggle defaults to the OS setting and remembers an explicit choice
in `localStorage` (`ogr-theme`). `index.html` applies it before first paint.
Colours are CSS custom properties defined per theme in `index.css`. Charts
set them through `style`, because `var()` does not resolve in SVG attributes.

# Troubleshooting

| Symptom | Likely cause |
|---|---|
| Header shows a `mock data` chip | `VITE_USE_MOCK_API=true` in `frontend/.env`. Restart `npm run dev` after changing it: Vite reads `.env` only at startup |
| Every request gets `503 OGR_API_KEY is not configured` | `OGR_API_KEY` is unset on the backend |
| Every request gets `401` | Not signed in, or the session expired or the backend restarted (sessions are held in memory). Sign in again |
| An action says it needs the admin key | You signed in with the viewer key while `OGR_ADMIN_KEY` is set. Sign out and sign in with the admin key |
| The frontend build stops on `VITE_API_KEY is set` | Remove `VITE_API_KEY` from `frontend/.env*`: the key is typed at sign-in now |
| CORS error in the browser console | The frontend origin is not in `OGR_CORS_ORIGINS`. Add it and restart the backend |
| `verify` fails on TigerGraph | `TG_HOST` must be the full `https://…` URL, the credentials must be valid, and `TG_CLOUD=true` is needed for Savanna |
| `verify` fails on the LLM with `429`/quota | The key has no quota left. Pick another provider/model in Settings, or use a local server (`LLM_BASE_URL=http://localhost:11434/v1`, no key needed) |
| Answers are empty / "not mentioned" for every question | `graph/client.py` does not raise when TigerGraph is unreachable or a query is missing. It logs a warning and returns `[]`. Check the backend log and `verify` before debugging a pipeline, and run `build` if Q1–Q5 are missing |
| A query opens "No matching embeddings" | The active embedding model has no complete embeddings for the loaded data. Pick an offered model, or finish the job in Settings (Resume / Complete) |
| Build returns `reset_required` | The graph predates dataset tracking or per-model embedding storage. Confirm "Reset graph and build" (this removes every loaded dataset) |
| Embedding switching is greyed out | A build, re-embed job or benchmark is running. It re-enables when that ends |
| `/dashboard`, `/build` or `/history` 404 on refresh of a deployed build | The SPA rewrite is missing. Keep both `netlify.toml` and `frontend/public/_redirects` (see `config-docs/DEPLOY.md`) |
| `npm ci` fails on Windows with "operation was rejected by your operating system" | A dev server or antivirus is holding `node_modules`. Stop the dev server first. `npm install` is more forgiving |

# Attribution

The corpus is derived from English Wikipedia (CC BY-SA 4.0). The embedding
models and software carry their own licences. See [`ATTRIBUTION.md`](ATTRIBUTION.md).
