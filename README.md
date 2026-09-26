# tigergraph-agentic-graph-rag

> **Picking this up fresh? Start at
> [`config-docs/CONTINUE.md`](config-docs/CONTINUE.md).** It covers what runs
> today, what does not and why, what you need to supply, and the ordered list
> of what to build next.
>
> **Current state in one line:** three pipelines, the GSQL query library, the
> ingestion path, the FastAPI service and the UI are all implemented and can
> run end to end against a real TigerGraph workspace and a real LLM — see
> [Getting started](#getting-started) below. Without those two credentials
> supplied, the frontend still runs on its own against fixture data
> (`VITE_USE_MOCK_API` defaults to `true`). [`config-docs/AUDIT.md`](config-docs/AUDIT.md)
> and [`config-docs/AUDIT-03.md`](config-docs/AUDIT-03.md) record what was
> checked and how.

Three pipelines — RAG, GraphRAG and Agentic GraphRAG — answering the same
questions over the same corpus, benchmarked to determine when a multi-step
agentic investigation beats simpler retrieval and when it is overkill once
token and complexity cost are counted.

This is the integration branch. It holds the `backend/` module (record
contracts, all three pipelines, ingestion, the GSQL query library, the
deterministic scorer/dispatcher/aggregator and the FastAPI service), the
`frontend/` module (three-column comparison UI, build view, dashboard and
per-question eval table), and the `scripts/` vector spike.

## Getting started

Two independent pieces run here: the **backend** (FastAPI + the three
pipelines + TigerGraph) and the **frontend** (the React UI). The frontend
works on its own with no backend at all — it defaults to fixture data — but
to see real answers from a real graph and a real LLM, both need to be running
at once, in two terminals, pointed at each other.

### Prerequisites

| Needed | Version | Why |
|---|---|---|
| Python | 3.11+ | Backend (FastAPI, the pipelines, ingestion) |
| Node.js | 20+ | Frontend (Vite, React) |
| A TigerGraph workspace | Savanna (cloud) or Community Edition 4.2+ | Vectors *and* the graph both live there — no FAISS/Chroma/pgvector substitute |
| An LLM endpoint | any OpenAI-compatible API | Intent parsing, generation, groundedness checks |

The TigerGraph workspace and LLM endpoint are only required to run the
**backend** for real. Skip both and just run the frontend (below) to explore
the UI on illustrative fixture data.

### 1. Configure the backend

From the repo root:

```bash
cp env.example .env
```

Fill in `.env`:

| Variable(s) | What to put there |
|---|---|
| `TG_HOST` | Your workspace endpoint (Savanna: workspace page → **Connect**) |
| `TG_TOKEN`, or `TG_USERNAME`/`TG_PASSWORD`, or `TG_SECRET`, or `TG_JWT_TOKEN` | Whichever credential style your workspace issues, in that order of preference — see the comment above `_connect()` in `backend/src/ogr/graph/client.py` if more than one is set |
| `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` (and `LLM_BASE_URL` for anything that isn't `api.openai.com`) | Any OpenAI-compatible endpoint — a paid key, a free-tier key, or a local server (Ollama, llama.cpp, vLLM) |
| `OGR_API_KEY` | Any string of 8+ characters. Required — the API refuses every request (except `/health`) until this is set. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(24))"` |

`OGR_CORS_ORIGINS` already defaults to the Vite dev server's origins
(`http://localhost:5173`), so it needs no change for local development.

`.env` is git-ignored. Never commit real values, and never put a secret in a
`VITE_`-prefixed variable — those are compiled into the browser bundle (see
"Swapping mock → real API" under Frontend, below).

### 2. Install and start the backend

```bash
pip install -e "backend[dev]"          # installs FastAPI, the pipelines, pytest, ruff
python -m ogr.cli verify               # confirms the LLM and TigerGraph endpoints are reachable
```

`verify` checks credentials without spending more than a few tokens or
touching the graph. If it reports the five GSQL queries (`q1_lookup` …
`q5_hybrid_search`) are **not** installed, run the one-time build first — it
chunks and embeds the corpus, installs the schema, loads the graph and
installs the queries (idempotent; safe to re-run):

```bash
python -m ogr.cli build                # only needed once per TigerGraph workspace
```

Then start the API:

```bash
python -m uvicorn ogr.api.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

Confirm it's up: `curl http://127.0.0.1:8000/health` → `{"status":"ok"}`.
Leave this running in its own terminal.

### 3. Install and start the frontend

In a second terminal:

```bash
cd frontend
npm install
cp .env.example .env
```

Edit `frontend/.env` to point at the backend you just started:

```bash
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_KEY=<the same value as OGR_API_KEY in the backend's .env>
```

```bash
npm run dev
```

Open **http://localhost:5173**. Submit a query on the Search screen — all
three pipeline columns, the trace panel and the verdict strip should fill in
with real data.

To skip all of this and just look at the UI, leave `frontend/.env` unset (or
`VITE_USE_MOCK_API=true`) and run only step 3 — no backend, no credentials,
no TigerGraph.

### Troubleshooting

| Symptom | Likely cause |
|---|---|
| Frontend shows a `MOCK DATA` badge in the header | `VITE_USE_MOCK_API` is `true` (or unset) in `frontend/.env` — restart `npm run dev` after changing it, Vite only reads `.env` at startup |
| Every backend request gets `401 Unauthorized` | `OGR_API_KEY` is unset on the backend, or doesn't match `VITE_API_KEY` on the frontend |
| Backend requests fail in the browser console with a CORS error | The frontend isn't running on an origin listed in `OGR_CORS_ORIGINS` (defaults to `localhost:5173`/`127.0.0.1:5173`) — add yours and restart the backend |
| `ogr.cli verify` fails on TigerGraph | Check `TG_HOST` is the full `https://…` workspace URL, and that exactly one credential style is filled in correctly |
| `ogr.cli verify` fails on the LLM with a `429`/quota error | The configured key has no remaining credit — swap in a different provider or a local server (`LLM_BASE_URL=http://localhost:11434/v1` for Ollama, no key needed) |
| A query pipeline returns "not mentioned" / empty citations for every question | `ogr.cli verify` passes but the five GSQL queries aren't installed yet, or the graph is empty — run `python -m ogr.cli build` |

## Documentation

The specs, implementation plans and audit records live in
[`config-docs/`](config-docs/):

| Document | What it is |
|---|---|
| [`CONTINUE.md`](config-docs/CONTINUE.md) | **Start here** — handoff: state, blockers, what to build next |
| [`APPLICATION-SPEC.md`](config-docs/APPLICATION-SPEC.md) | Functional and non-functional requirements (FR/NFR) |
| [`ARCHITECTURE-SPEC.md`](config-docs/ARCHITECTURE-SPEC.md) | C4 views, the seven agents, necessity routing, decision records |
| [`TECHNICAL-SPEC.md`](config-docs/TECHNICAL-SPEC.md) | Stack, graph schema, query library, record contracts, evaluation |
| [`BUILD-PLAN.md`](config-docs/BUILD-PLAN.md) | Task table, gates, branching model |
| [`implementation-plan-RAG.md`](config-docs/implementation-plan-RAG.md) | P1 plan |
| [`implementation-plan-GRAPH.md`](config-docs/implementation-plan-GRAPH.md) | P2 and the shared foundation |
| [`implementation-plan-AGENT.md`](config-docs/implementation-plan-AGENT.md) | P3 plan |
| [`implementation-plan-UI.md`](config-docs/implementation-plan-UI.md) | UI, scorer, dispatcher and batch plan |
| [`UI-SPEC.md`](config-docs/UI-SPEC.md) | Frontend contract — screens, states, data, formatting; design-tool ready |
| [`AUDIT.md`](config-docs/AUDIT.md) | What is implemented, what is not, and the evidence |
| [`INTEGRATION.md`](config-docs/INTEGRATION.md) | How the feature branches were merged |
| [`DEPLOY.md`](config-docs/DEPLOY.md) | Hosting the frontend on Netlify |

Source files cite these documents by name in their docstrings (for example
`Plan: implementation-plan-AGENT.md Group 4`); the names are unchanged, only
the directory moved.

# Backend

## Run it

See [Getting started](#getting-started) above for the full setup (`.env`,
TigerGraph, an LLM endpoint). Once configured:

```bash
pip install -e "backend[dev]"
python -m uvicorn ogr.api.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

| Command | What it does |
|---|---|
| `python -m ogr.cli verify` | Checks the LLM and TigerGraph endpoints are reachable, and whether Q1–Q5 are installed. Spends only a few tokens, changes nothing |
| `python -m ogr.cli build` | One-time per workspace: chunk + embed the corpus, install the schema, load the graph, install Q1–Q5. Idempotent |
| `python -m ogr.cli ask "<question>" --pipelines rag,graphrag,agentic_graphrag` | Answer one question from the terminal, without the API or frontend |
| `python -m ogr.cli batch <questions.jsonl> --out out/run.jsonl` | Run a full question set through all three pipelines (`EVAL-04`) |
| `python -m uvicorn ogr.api.main:app --app-dir backend/src --port 8000` | Start the HTTP API the frontend talks to |
| `cd backend && pytest -q` | Run the test suite |
| `cd backend && ruff check src tests` | Lint |

Or, from a clean clone with `.env` filled in, `make reproduce` runs
`install → check → verify → build → benchmark → timing → holdout` in one go
(see `Makefile`).

## P1 Baseline (Honest Unfiltered RAG)

The P1 baseline pipeline implements standard, unfiltered Retrieval-Augmented Generation (RAG) over the entire document corpus. By architectural decision (AD-9), P1 receives **no type filtering, no candidate sets, no relevance thresholds, and no re-ranking**. Because the corpus contains 26.7% non-Olympic documents (including films, officeholder biographies, and tennis tournaments), unfiltered dense retrieval exposes the fundamental ceiling of standard text vector search on complex multi-hop, aggregation, and domain-specific questions. P1's ceiling is deliberately visible rather than masked; masking or type-filtering this baseline would quietly rig the three-way comparison against GraphRAG (P2) and Agentic GraphRAG (P3).

## Where the LLM is, and is not

**No LLM sits in the scoring path.** Exact match and token F1 are computed
deterministically against the verified gold answers (SQuAD-style normalization),
so the reported numbers are reproducible run-to-run for identical inputs
(NFR-6, AD-4). Verified gold answers already exist; a reference-free LLM judge
is the tool for the *absence* of ground truth, not a weaker substitute when
labels are present.

The Agentic pipeline (P3) does make **one** LLM call inside its evidence
evaluator, a groundedness check that asks whether the retrieved evidence can
answer the question (DP-4). That is a **retrieval decision** — it determines
whether the agent keeps investigating — and it never contributes to a score.
The evaluator's first stage, the scope-coverage gate, is fully deterministic.
Stating this plainly because the Evidence Evaluator is described elsewhere as
"deterministic" while performing a groundedness check, which reads as a
contradiction until the two roles are separated.

Every model call in P3 is routed through one accounting module and attributed
to a numbered trace step, and the sum of per-step tokens is reconciled against
the record total. Where a provider reports no usage, the model's own tokenizer
is used and the figure is labelled `local_tokenizer`; where the model exposes
no tokenizer either, the figure is labelled `estimated` rather than being
presented as a count.

## What P3's agent design actually is

P3 is a deterministic `StateGraph` with exactly **two** LLM touchpoints per
run — the intent parse and, when the loop runs, one groundedness check per
iteration. Routing (LOOKUP-direct vs. scoped-aggregate vs. loop), the
stopping decision, and fallback tool selection are all plain Python, not
model choices. Read the design as "deterministic orchestration with minimal
LLM touchpoints," not free-form multi-tool ReAct — the model never chooses
which tool to call next.

## A caveat on the measured lift

P3 can accumulate evidence across up to `RUN_MAX_STEPS` (default 6) loop
iterations plus fallback tools, while P1 takes a single k=10 vector-search
shot per AD-9. Part of any accuracy lift P3 shows over P1 is therefore "more
retrieval attempts," not purely "smarter retrieval" — both are real
properties of the architectures being compared, but they are not the same
claim, and the submission should say so rather than let a reader assume the
whole gap is investigative skill.

# Frontend

## Run it

```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

Then open http://localhost:5173. No backend is required — `VITE_USE_MOCK_API`
defaults to `true`. To run this against a real backend instead of fixtures,
see [Getting started](#getting-started) above.

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server on :5173 |
| `npm run build` | Type-check (`tsc --noEmit`) then production build into `frontend/dist` |
| `npm run preview` | Serve the production build |
| `npm run lint` | ESLint over `src` |
| `npm test` | Vitest (jsdom) |

## Screens

| Route | Screen | Covers |
|---|---|---|
| `/` | Three-column query comparison, live trace panel, verdict strip | FR-1 … FR-10 |
| `/build` | Choose or upload a dataset (JSONL in `data/corpus/`), build it into the shared graph — other datasets stay loaded; an already-built dataset asks Rebuild or Cancel — with per-pipeline readiness | PLAN-004 Group 4, DP-6 A, DP-7 A |
| `/benchmarks` | Two tabs: **Dashboard** (aggregate view over one batch run, TECHNICAL-SPEC §10) and **Run benchmark** (run, history, import/export, compare) | FR-13, FR-15 |
| `/eval` | Every question × three pipelines, with drill-down | FR-20, PLAN-004 Group 5 |
| `/history` | Every query, build and benchmark attempt (`out/history.jsonl`) with filters and search | — |

`/benchmarks` (dashboard tab) and `/eval` read a run id from `?run=`; on a live
backend they open the newest run, in mock mode `latest`. `/dashboard` redirects. The mock
transport ships two runs: `latest` (20 scored questions) and `hidden` (8
questions with no gold, so the gold and score columns disappear — the same
component renders the hidden set).

## Light and dark mode

The toggle sits in the header. It defaults to the OS setting
(`prefers-color-scheme`) and remembers an explicit choice in `localStorage`
under `ogr-theme`; `index.html` applies the value before first paint so there is
no flash. Every colour is a CSS custom property defined twice in `index.css` —
once under `:root, :root[data-theme='dark']` and once under
`:root[data-theme='light']`. Chart colours reference the same tokens
(`components/colors.ts`), so bars, swatches and scatter points follow the
switch. Because `var()` only resolves in CSS, SVG shapes set them via `style`
rather than the `fill`/`stroke` attributes.

## Folder structure

```
frontend/
  .env.example              every configurable value, including the mock switch
  src/
    config.ts               the single config point (base URL, API key, mock switch)
    types.ts                the §6 data model — PipelineRecord, TraceStep, BatchRecord, …
    format.ts               number/duration formatting, mean, median
    main.tsx  App.tsx       router shell
    SearchView.tsx          three-column query surface
    TracePanel.tsx          live agentic trace (also reused in the eval drill-down)
    BuildView.tsx           three-column ingestion build
    Dashboard.tsx           aggregate benchmark view
    EvalTable.tsx           per-question table with drill-down
    components/             QueryInput, ResultColumn, VerdictStrip, CitationList,
                            StatusBadge, RunPicker, Charts, colors
    services/
      http.ts               fetch wrapper (X-API-Key) + EventSource helper
      queryService.ts       POST /query, GET /query/{id}/stream, GET /query/{id}/result
      buildService.ts       POST /build, GET /build/{id}/stream
      batchService.ts       GET /batch/{run_id}/records
      mock/transport.ts     fixture replay against a wall clock
    fixtures/               JSON shaped to the API contracts
```

No state store: local component state is sufficient for four screens.

## Swapping mock → real API

Set two values in `frontend/.env`:

```bash
VITE_USE_MOCK_API=false
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_KEY=<the value of OGR_API_KEY on the backend>
```

Nothing else changes. Components never touch fixtures — they call
`services/*Service.ts`, and each service branches on `config.useMockApi` at its
boundary. The real branch is already written against the spec'd endpoints:

| Call | Endpoint |
|---|---|
| `submitQuery` | `POST /query` → `202 {query_id, stream_token}` |
| `openQueryStream` | `GET /query/{id}/stream?token=…` (SSE) |
| `getQueryResult` | `GET /query/{id}/result` |
| `listCorpora` | `GET /corpora` — datasets in `data/corpus/` and which are loaded (`out/datasets.json`) |
| `uploadCorpus` | `POST /corpora/{name}` — body is the JSONL (`doc_id`, `text` required per line) |
| `startBuild` | `POST /build` `{dataset, rebuild, reset}` → `202 {build_id, stream_token}`; `409 {code: already_built \| reset_required \| build_running}` asks first |
| `getHistory` | `GET /history?kind=` — every attempt, newest first |
| `openBuildStream` | `GET /build/{id}/stream?token=…` (SSE) |
| `getBatchRecords` | `GET /batch/{run_id}/records` |
| `listRuns` | `GET /runs` — one summary per stored run: `run_config` metadata plus per-pipeline EM/F1/P/R, tokens, latency, errors, F1 per 1k tokens |
| `listDatasets` | `GET /datasets` — question files in `data/questions/` |
| `startBenchmark` | `POST /batch` `{dataset}` → `202 {run_id}`; records append to `out/{run_id}.jsonl` as questions complete |
| `importRun` | `POST /runs/import` — a run's JSON export (`{run_id, run_config, records}`), a bare record list, or its native JSONL file; an existing run id is refused (409) |

`X-API-Key` goes on every request. The SSE endpoints take the short-lived
single-use `stream_token` as `?token=` instead, because browser `EventSource`
cannot send headers (DP-8).

### SSE events the backend must emit

`GET /query/{id}/stream` uses named events:

| Event | Payload | Why |
|---|---|---|
| `trace` | one `TraceStep` | fills the trace panel as the agent works |
| `pipeline` | one `PipelineRecord` | lets a column render the moment *its* pipeline finishes, independent of the other two (FR-3, FR-4) |
| `done` | any | all three settled; the UI then fetches `/query/{id}/result` for the verdict |


`GET /build/{id}/stream` emits `build` (one `BuildEvent`) and `done`; a failed
stage is a `build` event with `status: error`. A dropped stream is recovered
from `GET /query/{id}/result` (query) or shown as failed.
`BuildEvent.status` is `running | done | error | ready`; a `ready` event flips
the readiness badge for the pipelines it names.

## Fixture data

`src/fixtures/*.json` is **illustrative, not measured**. The wikidata QIDs,
answers and timings are plausible stand-ins so every screen and state can be
exercised without a backend. Build timings are compressed to ~14 s of replay; a
real ingest of 2,951 documents takes far longer.

## Attribution

The Olympic Wikipedia corpus the backend ingests is CC BY-SA 4.0. See
`ATTRIBUTION.md` when the ingestion path lands.
