# tigergraph-agentic-graph-rag

Frontend for the Agentic GraphRAG three-pipeline comparison system: one query,
three pipelines (RAG / GraphRAG / Agentic GraphRAG) executed concurrently, shown
side by side with a live agentic trace and a cost/accuracy verdict.

**This repository currently contains the UI only.** The FastAPI backend is built
separately. Every screen runs today against fixture data through a mock
transport, and swapping to the real API is one environment variable.

## Run it

```bash
cd frontend && npm install && cp .env.example .env && npm run dev
```

Then open http://localhost:5173. No backend is required — `VITE_USE_MOCK_API`
defaults to `true`.

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
| `/build` | Three-column ingestion build with per-pipeline readiness | PLAN-004 Group 4, DP-6 A, DP-7 A |
| `/dashboard` | Aggregate benchmark view over one batch run | TECHNICAL-SPEC §10 |
| `/eval` | Every question × three pipelines, with drill-down | FR-20, PLAN-004 Group 5 |

`/dashboard` and `/eval` read a run id from `?run=` (default `latest`). The mock
transport ships two runs: `latest` (20 scored questions) and `hidden` (8
questions with no gold, so the gold and score columns disappear — the same
component renders the hidden set).

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
| `startBuild` | `POST /build` → `202 {build_id, stream_token}` |
| `openBuildStream` | `GET /build/{id}/stream?token=…` (SSE) |
| `getBatchRecords` | `GET /batch/{run_id}/records` |

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
| `error` | `{detail}` | stream-level failure |

`GET /build/{id}/stream` emits `build` (one `BuildEvent`), `done` and `error`.
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
