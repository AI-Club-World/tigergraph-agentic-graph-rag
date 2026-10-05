# tigergraph-agentic-graph-rag

Three pipelines — RAG, GraphRAG and Agentic GraphRAG — answer the same
questions over the same corpus, side by side. The benchmark shows when a
multi-step agentic investigation beats simpler retrieval, and when it is
overkill once tokens, latency and complexity are counted.

The repo holds:

- `backend/`: the FastAPI service, the three pipelines, ingestion, the GSQL
  schema and query library, the deterministic scorer/dispatcher/aggregator, the
  batch runner and the CLI.
- `frontend/`: the React UI, with Search, Build, Dashboard and History screens
  and a Settings panel.
- [`embedding_server_2.ipynb`](embedding_server_2.ipynb): dual-GPU Kaggle notebook
  serving the 5 catalog embedding models (GPU 0) and Ollama Gemma 4 12B (GPU 1)
  over FastAPI and an ngrok tunnel.

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
| [`embedding_server_2.ipynb`](embedding_server_2.ipynb) | Kaggle dual-GPU embedding & LLM server notebook with ngrok / Cloudflare tunnel |
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
| An embedding backend | Cloudflare Workers AI credentials, local `sentence-transformers`, or the Kaggle GPU host (`embedding_server_2.ipynb`) | Chunk and query embeddings |

### Optional: Run the Embedding & LLM Server on Kaggle (`embedding_server_2.ipynb`)

If you do not have local GPU hardware or Cloudflare Workers AI credentials, you can host the 5 catalog embedding models and Ollama on a free Kaggle GPU instance (2× T4) using [`embedding_server_2.ipynb`](embedding_server_2.ipynb):

- **GPU 0 (~6 GB VRAM)**: Loads all 5 catalog embedding models (`bge-large-en-v1.5`, `qwen3-embedding-0.6b`, `embeddinggemma-300m`, `gte-large-en-v1.5`, `mxbai-embed-large-v1`) and serves them via FastAPI (`/models`, `/embed`, `/health`, `/embed/status`).
- **GPU 1 (~8 GB VRAM)**: Runs Ollama serving Google's official `gemma4:12b` chat model (`/chat`, `/chat/status`).
- **Tunnel**: Exposes the FastAPI server to the internet via ngrok Agent Endpoint (with automatic fallback to Cloudflare Quick Tunnel).

#### Steps to launch on Kaggle:

1. **Import Notebook**: On [Kaggle](https://www.kaggle.com/code), click **New Notebook** → **File** → **Import Notebook** → select [`embedding_server_2.ipynb`](embedding_server_2.ipynb).
2. **Session Settings**:
   - In the right sidebar under **Notebook options**, set **Accelerator** to **GPU T4 x2**.
   - Make sure **Internet on** is toggled on.
3. **Configure Secrets** (**Add-ons** → **Secrets** in the notebook menu):
   - `HF_TOKEN`: Hugging Face user access token (required for `embeddinggemma-300m`; accept the model agreement on [Hugging Face](https://huggingface.co/google/embeddinggemma-300m) first).
   - `NGROK_AUTHTOKEN`: Auth token from [ngrok dashboard](https://dashboard.ngrok.com/get-started/your-authtoken).
   - *(Optional)* `NGROK_COMMAND` or `NGROK_URL`: Custom domain or agent command from your ngrok dashboard (if omitted, ngrok assigns a random URL; if ngrok fails, it falls back to Cloudflare Quick Tunnel).
4. **Run Cells**: Execute Cells 1 through 6 sequentially.
   - Once Cell 5 completes, it checks readiness and prints:
     ```text
     ============================================================
     EXECUTION COMPLETE -- SERVER IS LIVE AND READY
     ============================================================
     Tunnel         : ngrok (your ngrok endpoint)
     Public URL     : https://your-name.ngrok-free.app
     ```
   - Cell 6 continues running to keep the server alive and prevent kernel shutdown.
5. **Point Backend to Kaggle**: Copy the `Public URL` into your local `.env`:
   ```bash
   EMBEDDING_HOST_URL=https://your-name.ngrok-free.app
   ```
   *(Optional)* If you also wish to use the Kaggle Ollama server as your chat LLM:
   ```bash
   LLM_PROVIDER=openai_compatible
   LLM_MODEL=gemma4:12b
   LLM_BASE_URL=https://your-name.ngrok-free.app/v1
   LLM_API_KEY=ollama
   ```
   Verify health with `curl https://your-name.ngrok-free.app/health` or `python -m ogr.cli verify --pre-build`.

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
| `EMBEDDING_HOST_URL` | Optional self-hosted embedding service serving the catalog models: `POST {url}/embed` with `{"model": "<key>", "texts": [...]}` returns `{"embeddings": [...]}` (e.g. from `embedding_server_2.ipynb`). Tried first; on failure the next tier runs |
| `EMBEDDING_CLOUDFLARE`, `EMBEDDING_REMOTE` | `false` skips the Cloudflare embedding tier (e.g. quota spent), or every remote tier. Both default to `true` |
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
cp .env.example .env    # no key here: the application is open
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

## Access

The application is open: there is no sign-in, API key or role, and every
route can be called without credentials. Anyone who can reach the backend can
build or reset the graph, upload datasets, switch embedding models, change the
LLM and start benchmarks. Run it on a trusted network, or put a reverse proxy
with its own authentication in front of it for a public deployment.

Backend secrets (`TG_*`, `LLM_API_KEY`, provider keys, `CLOUDFLARE_API_TOKEN`)
stay in the backend `.env`. They never go in the frontend: the frontend build
refuses to run with a `VITE_API_KEY` set, because every `VITE_` value is
compiled into the public bundle.

# Backend

## CLI (`python -m ogr.cli`)

| Command | What it does |
|---|---|
| `verify [--pre-build]` | Checks the LLM, the embedding backend and TigerGraph, and whether Q1–Q5 are installed. Exit code 0 only when nothing fails |
| `build [--corpus PATH] [--vector-timeout S]` | Full reset and load of one corpus, as described above |
| `batch QUESTIONS.jsonl --out OUT.jsonl [--run-id ID] [--mode throughput\|timing] [--embedding-model KEY]` | Runs a question set through all three pipelines and appends one scored record per question (details below). Logs a `benchmark` entry to the History screen |
| `ask "<question>" [--pipelines rag,graphrag,agentic_graphrag] [--embedding-model KEY] [--json] [--show-trace]` | Answers one question from the terminal. Default pipeline: `rag`. Aliases: `graph`, `agentic` |
| `coverage [--corpus PATH] [--out out/ingest-coverage.md]` | Parses the corpus infoboxes and writes the ingest coverage report |
| `report RUN.jsonl [--out REPORT.md]` | Markdown run report: EM/F1/completeness/grounding and token cost per pipeline; per question type the Agentic − RAG gap, token ratio and a worth-it verdict; necessity routing (direct vs loop, with a labelled token-savings estimate); agents, tools and stop reasons |
| `export RUN.jsonl --out EXPORT.json` | Submission JSON: per question and pipeline the answer, explanation, tokens, latency, citations (with evidence snippets) and, for Agentic, the full trace |

How `batch` behaves:

- **Run id.** Defaults to a UTC timestamp. The mode defaults to `RUN_LATENCY_MODE`. `timing` runs with a pool size of 1, so its latencies are comparable.
- **Where the app finds it.** The Dashboard and Eval table read `out/<run_id>.jsonl` on the machine running the API. Any other `--out` path prints a note and the run does not show there. `out/` is git-ignored: a run made on another machine or in a cloud session reaches the app only by copying that file into `out/` or through **Import** (the JSONL, or the `export` JSON).
- **Resume.** Rerunning the same command against an existing `--out` file skips every question already recorded successfully. A question whose latest record has a pipeline error is retried, and the new record supersedes the old one.
- **Stops and exit codes.** A rate-limit error stops the run: no new question starts. If any question was not recorded, or the `RUN_MAX_TOTAL_TOKENS` ceiling was reached, the command exits 1 with the reason. The ceiling counts tokens across resumes. Rerun to continue.

Tests and lint: `cd backend && pytest -q` and `cd backend && ruff check src tests`.

## HTTP API

Routes from `backend/src/ogr/api/main.py`. None needs credentials (see
Access).

| Method and path | Purpose |
|---|---|
| `GET /health` | Liveness: `{"status":"ok"}` |
| `GET /health/db`, `/health/llm`, `/health/embedding` | One dependency check each. Results are cached for 30 s, and hosts are redacted |
| `GET /settings` | Effective LLM provider/model and embedding model (no secrets) |
| `GET /settings/providers` | Gemini / NVIDIA NIM / Groq presets and whether each key is set |
| `GET /settings/models?provider=` | That provider's live model list. NVIDIA is narrowed to free endpoints |
| `PATCH /settings` | Change the provider/model at runtime. Also switches the embedding model when the target is already complete |
| `GET /embeddings` | Each embedding model's state, the 2-model cap and the current job |
| `GET /embeddings/plan?model=` | What switching to `model` would do |
| `POST /embeddings/switch` | Switch the embedding model. `mode` is `replace` or `parallel`. At the cap, `evict` names the model to delete |
| `POST /embeddings/resume` | Continue a failed re-embed job from its last batch |
| `POST /embeddings/{model}/complete` | Embed the chunks a stored model is missing |
| `POST /query` | `{query, embedding_model?}` → `202 {query_id}`. Returns `409 embedding_mismatch` when the model has no complete embeddings |
| `GET /query/{id}/stream` | SSE: `trace`, `pipeline`, `done` |
| `GET /query/{id}/result` | The merged `QueryLevelRecord`. Returns `409` while the query is still running |
| `GET /corpora` | Datasets in `data/corpus/` with display names, and which are loaded. With no dataset recorded in `out/datasets.json` (a fresh install against a graph built elsewhere), `graph.live` carries TigerGraph's own vertex counts |
| `POST /corpora/{name}` | Upload a JSONL dataset (the request body is the file). Options: `unique`, `overwrite`, `title`, `source_file` |
| `PATCH /corpora/{name}` | Rename a dataset (`title`, `description`) |
| `POST /build` | `{dataset, rebuild, reset}` → `202 {build_id}`. Returns `409` with `already_built`, `reset_required`, `build_running`, `embedding_job_running`, `batch_running` or `embedding_cap` |
| `GET /build/current` | The latest build and its events, so a reloaded page can resume following it |
| `GET /build/{id}/stream` | SSE: `build`, `done` |
| `GET /datasets` | Question sets in `data/questions/` |
| `POST /batch` | `{dataset, run_id?, latency_mode?, resume?}` → `202 {run_id, status}`. Records go to `out/{run_id}.jsonl` |
| `GET /runs` | One summary per stored run, newest first |
| `POST /runs/import` | Import a run export, a record list, a native JSONL file or an `ogr.cli export` file (imported unscored: it carries no gold). Returns `409` if the run id already exists |
| `GET /batch/{run_id}/records` | A run's scored records |
| `GET /history?kind=&limit=` | Every query, build, benchmark and embedding-job attempt (`out/history.jsonl`), newest first |

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
      http.ts             fetch wrapper (ApiError) + EventSource helper
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
| The frontend build stops on `VITE_API_KEY is set` | Remove `VITE_API_KEY` from `frontend/.env*`: the application needs no key |
| A fresh checkout against a graph built elsewhere | Handled: on startup (and before listing datasets, building, querying or benchmarking) the backend rebuilds `out/datasets.json` and `out/embeddings.json` from TigerGraph when this install has neither, provided every document in the graph comes from one file in `data/corpus/` (`ingest/adopt.py`). Otherwise the Build screen shows TigerGraph's own counts |
| CORS error in the browser console | The frontend origin is not in `OGR_CORS_ORIGINS`. Add it and restart the backend |
| `verify` fails on TigerGraph | `TG_HOST` must be the full `https://…` URL, the credentials must be valid, and `TG_CLOUD=true` is needed for Savanna |
| `verify` fails on the LLM with `429`/quota | The key has no quota left. Pick another provider/model in Settings, use a local server (`LLM_BASE_URL=http://localhost:11434/v1`, no key needed), or run the Kaggle GPU server (`embedding_server_2.ipynb`) |
| Answers are empty / "not mentioned" for every question | `graph/client.py` does not raise when TigerGraph is unreachable or a query is missing. It logs a warning and returns `[]`. Check the backend log and `verify` before debugging a pipeline, and run `build` if Q1–Q5 are missing |
| A query opens "No matching embeddings" | The active embedding model has no complete embeddings for the loaded data. Pick an offered model, or finish the job in Settings (Resume / Complete) |
| `EMBEDDING_HOST_URL` fails or times out | If using `embedding_server_2.ipynb` on Kaggle, ensure Cell 6 is still running and check that the tunnel URL has not expired or changed |
| Build returns `reset_required` | The graph predates dataset tracking or per-model embedding storage. Confirm "Reset graph and build" (this removes every loaded dataset) |
| Embedding switching is greyed out | A build, re-embed job or benchmark is running. It re-enables when that ends |
| `/dashboard`, `/build` or `/history` 404 on refresh of a deployed build | The SPA rewrite is missing. Keep both `netlify.toml` and `frontend/public/_redirects` (see `config-docs/DEPLOY.md`) |
| `npm ci` fails on Windows with "operation was rejected by your operating system" | A dev server or antivirus is holding `node_modules`. Stop the dev server first. `npm install` is more forgiving |

# Attribution

The corpus is derived from English Wikipedia (CC BY-SA 4.0). The embedding
models and software carry their own licences. See [`ATTRIBUTION.md`](ATTRIBUTION.md).
