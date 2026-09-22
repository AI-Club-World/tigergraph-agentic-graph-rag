# tigergraph-agentic-graph-rag

> **Picking this up fresh? Start at
> [`config-docs/CONTINUE.md`](config-docs/CONTINUE.md).** It covers what runs
> today, what does not and why, what you need to supply, and the ordered list
> of what to build next.
>
> **Current state in one line:** three pipelines and the UI are implemented and
> unit-tested (185 backend tests green), but the system has **never run
> end to end** — there is no ingestion code, there are no GSQL queries, and
> there is no HTTP API, so the frontend runs on fixtures.

Three pipelines — RAG, GraphRAG and Agentic GraphRAG — answering the same
questions over the same corpus, benchmarked to determine when a multi-step
agentic investigation beats simpler retrieval and when it is overkill once
token and complexity cost are counted.

This is the integration branch. It holds the `backend/` module (record
contracts, all three pipelines, the deterministic scorer, dispatcher and
aggregator), the `frontend/` module (three-column comparison UI, build view,
dashboard and per-question eval table), and the `scripts/` vector spike.

The frontend still runs against fixture data by default — `VITE_USE_MOCK_API`
defaults to `true` — because the FastAPI service that joins the two modules
(`API-01`) is not built yet. [`config-docs/AUDIT.md`](config-docs/AUDIT.md)
records what is implemented and what is not.

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
| [`AUDIT.md`](config-docs/AUDIT.md) | What is implemented, what is not, and the evidence |
| [`INTEGRATION.md`](config-docs/INTEGRATION.md) | How the feature branches were merged |
| [`DEPLOY.md`](config-docs/DEPLOY.md) | Hosting the frontend on Netlify |

Source files cite these documents by name in their docstrings (for example
`Plan: implementation-plan-AGENT.md Group 4`); the names are unchanged, only
the directory moved.

# Backend

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

# Frontend

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
