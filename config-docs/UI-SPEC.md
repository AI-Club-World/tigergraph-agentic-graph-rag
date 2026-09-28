# UI Specification — Agentic GraphRAG, Three-Pipeline Comparison

**Purpose.** A complete, implementation-independent description of the existing
frontend, written so the UI can be rebuilt in a different tool (design tool, AI
UI generator, another framework) **without losing a single behaviour**.

**Read this as:** *behaviour and data are normative; visual design is
reference-only.* Everything under "Behaviour", "Data", "States", "Formatting",
"Derived values" and "Contract to preserve" must survive the redesign. Anything
described as current visual treatment is what exists today and may be replaced
freely.

Source of truth for the current implementation: `frontend/src/`. Requirement IDs
(`FR-n`, `NFR-n`) refer to [`APPLICATION-SPEC.md`](APPLICATION-SPEC.md).

---

## 1. What this product is

One question is asked of **three pipelines at once** — RAG, GraphRAG and Agentic
GraphRAG — and the UI shows, side by side, what each one answered, what it cost
in tokens and latency, what it cited, and (for the agentic one) every step it
took and why it stopped. A benchmark area then aggregates the same records over
a whole evaluation run.

The research question the UI exists to answer: **when is a multi-step agentic
investigation worth its token cost, and when is it overkill?** Every screen is in
service of that comparison. Any redesign that makes the three-way comparison
harder to read has failed, however pretty it is.

### 1.1 The three pipelines

Fixed ids, order and labels. The order `rag → graphrag → agentic_graphrag` is
used everywhere (columns, table column groups, legends, tables) and must not be
reordered.

| id | Label | Subtitle shown on the search columns |
|---|---|---|
| `rag` | RAG | Q5 vector top-k, no type filtering |
| `graphrag` | GraphRAG | Shared intent parser, exactly one query, no loop |
| `agentic_graphrag` | Agentic GraphRAG | Intent parse, necessity routing, evidence check, optional re-query |

Each pipeline has one identity colour used consistently across columns, table
swatches, chart series and citation ref-type tags (§12).

---

## 2. Information architecture

Client-side routing (`frontend/src/App.tsx`), four screens, two redirects
and a not-found:

| Route | Screen | Purpose |
|---|---|---|
| `/` | **Search** (compare) | Ask one question, watch three pipelines answer live (§6) |
| `/build` | **Build** | Choose, upload or rename a dataset and build it into the shared graph, watching each pipeline become answerable (§7) |
| `/dashboard` | **Dashboard** | Three tabs, selected by `?tab=`: `dashboard` (aggregate view, §8, the default), `runs` (Run benchmark: execute, history, import/export, compare, §10.4) and `eval` (Eval table, §9) |
| `/history` | **History** | Every query, build, benchmark and embedding-job attempt (§18) |
| `/benchmarks` | redirect | → `/dashboard?tab=runs`, other query parameters (e.g. `?run=`) kept |
| `/eval` | redirect | → `/dashboard?tab=eval`, other query parameters kept |
| anything else | Not found | Renders the text `Not found.` |

The Dashboard and Eval table tabs read the run id from `?run=<run_id>`. This
must stay a URL parameter because those views are meant to be linkable.
Switching tabs keeps `?run=`. When `?run=` is absent:

- **Live backend, with `VITE_DEFAULT_RUN_ID` unset or `latest`:** the view
  lists runs (`GET /runs`, newest first) and writes the newest run's id into
  `?run=`, replacing the history entry. Live run ids are timestamps, so no run
  is ever named `latest`. With no runs at all, the view shows
  `No benchmark runs yet — start one from the Benchmarks view.`
- **Otherwise** (mock mode, or a different `VITE_DEFAULT_RUN_ID`): that id
  is loaded as given.

Each routed view sits inside an error boundary that resets on navigation.

### 2.1 App shell

A persistent header sits above the routed view:

- **Brand**: title `Agentic GraphRAG`, with the muted subtitle
  `Three-pipeline comparison`.
- **Nav**: `Search` (exact match on `/`), `Build`, `Dashboard`, `History`.
  The active route must be visually distinct.
- **Mock-data flag** (right side, **only when `useMockApi` is true**): a chip
  reading `mock data`, with the tooltip
  `VITE_USE_MOCK_API=true — every screen is served from src/fixtures`.
  This is a correctness feature, not decoration: it stops anyone reading
  fixture numbers as real results. It must remain visible and unmissable.
- **Service status bar** (right side, **live mode only**): three indicators,
  `Knowledge Base (TigerGraph)`, `Intelligent Engine (LLM)` and
  `Embedding Model`. They poll `GET /health/db`, `/health/llm` and
  `/health/embedding` independently, every `VITE_POLL_INTERVAL_MS`. A `⟳`
  button re-checks immediately. A failed API call (network error or 5xx) also
  triggers a re-check. Each indicator's tooltip gives the state and the
  server's detail.
- **Settings button** (gear icon, `aria-label="Open settings"`, **live mode
  only**) opens the Settings panel (§19).
- **Theme toggle** (right side): a sun icon in dark mode, a moon icon in
  light mode. `aria-label` and `title` both read `Switch to {light|dark} mode`,
  naming the *target* mode.

**Service gate.** When a service a feature needs is reported down, the
feature's controls are replaced by a `Feature unavailable` block. The block
names the offline services and has a `mailto:` contact link
(`VITE_ADMIN_EMAIL`). Gates:

| Feature | Needs |
|---|---|
| Search console | TigerGraph, LLM, embedding |
| `Start build` | TigerGraph, embedding |
| `Run benchmark` | TigerGraph, LLM, embedding |

The header is sticky at the top of the viewport. The content area is
width-capped (1600px) and centred.

---

## 3. Data model (normative)

Verbatim from `frontend/src/types.ts`. Field names come from the backend record
contract — **do not rename them**, including the snake_case.

```ts
type PipelineId = 'rag' | 'graphrag' | 'agentic_graphrag'
const PIPELINE_IDS = ['rag', 'graphrag', 'agentic_graphrag'] as const

type QType = 'lookup' | 'multi_hop' | 'temporal' | 'aggregation' | 'superlative'
const QTYPES = ['lookup', 'multi_hop', 'temporal', 'aggregation', 'superlative'] as const

type AgentType =
  | 'orchestrator' | 'entity_linking' | 'graph_traversal' | 'similarity_search'
  | 'document_retrieval' | 'aggregation' | 'multi_hop_reasoning'
  | 'evidence_evaluation' | 'answer_generation'

interface TokenUsage { input: number; output: number; total: number }

interface Citation {
  source_id: string            // parent doc_id (wikidata QID) — the scored field
  chunk_id: string | null      // displayed only, never scored
  ref_type: 'chunk' | 'entity' | 'relationship'
}

interface TraceStep {
  step_n: number
  agent_type: AgentType
  tool_called: string
  tokens: { input: number; output: number }   // note: no `total` here
  chunks_returned: number
  citations_count: number
  latency_ms: number
  strategy_change: boolean
  notes: string
}

interface PipelineRecord {
  pipeline: PipelineId
  answer: string               // shortest span — this is what EM/F1 score
  explanation: string          // prose with citations — displayed, never scored
  citations: Citation[]
  chunks_returned: number
  citations_count: number
  tokens: TokenUsage
  token_source: 'provider' | 'local_tokenizer' | 'estimated'
  latency_ms: number
  trace: TraceStep[] | null    // non-null only for agentic_graphrag
  strategy_changed: boolean | null
  stop_reason: string | null
  status: 'done' | 'error'
  error_detail: string | null
}

interface Verdict {
  token_multiplier_vs_rag: number | null      // null: a pipeline errored, or the baseline spent no tokens
  token_multiplier_vs_graphrag: number | null
  accuracy_delta_vs_rag: number | 'n/a'
  accuracy_delta_vs_graphrag: number | 'n/a'
  summary_line: string
}

interface QueryLevelRecord {
  query_id: string
  query_text: string
  qtype: QType | null
  timestamp: string            // ISO 8601
  pipelines: Record<PipelineId, PipelineRecord>
  verdict: Verdict
}

interface PipelineScores {
  em: number; f1: number; precision: number; recall: number; completeness: number
}                              // all 0..1; completeness is an explicit alias of recall

interface BatchRecord {
  run_id: string
  qid: string
  question: string
  qtype: QType | null
  ground_truth: string[]       // gold variants; EMPTY for a hidden set
  gold_doc_ids: string[]
  record: QueryLevelRecord
  scores: Record<PipelineId, PipelineScores> | null   // NULL for a hidden set
}

interface BuildEvent {
  stage: string
  pipeline_affected: PipelineId[]
  status: 'running' | 'done' | 'error' | 'ready'
  items_done: number
  items_total: number
  elapsed_ms: number
  tokens: number               // always 0 — building calls the embedding model, never an LLM
  note: string                 // on an `error` event: the failure reason
}

interface QueryAccepted { query_id: string; stream_token: string }
interface BuildAccepted { build_id: string; stream_token: string }

interface PipelineSummary {    // one pipeline's aggregate in GET /runs
  em: number | null; f1: number | null; precision: number | null; recall: number | null
  mean_tokens: number | null; median_tokens: number | null; total_tokens: number
  mean_latency_ms: number | null; errors: number; f1_per_1k_tokens: number | null
}

interface RunSummary {
  run_id: string
  status: 'running' | 'complete' | 'failed'
  error?: string               // why a failed run stopped (e.g. the LLM's rate limit)
  started_at: string
  dataset: string | null
  run_config: Record<string, string | number | boolean | null>
  n_questions: number
  scored: boolean
  pipelines: Partial<Record<PipelineId, PipelineSummary>>
}

interface RunExport { run_id: string; run_config: Record<string, …>; records: BatchRecord[] }
```

The dataset, history and settings shapes are in
`services/datasetService.ts`, `services/historyService.ts` and
`services/settingsService.ts`.

Two nullability rules drive whole screens and are easy to lose in a rewrite:

1. **`scores === null`** (a hidden/holdout run) → every accuracy column, table
   and chart disappears; token/latency/trace aggregations still render, with an
   explanatory note. Never render `0` or `—` in place of an absent score without
   the note.
2. **`accuracy_delta_* === 'n/a'`** → the verdict strip shows `N/A` in a warning
   tone **and keeps the field** (FR-9). Do not omit the tile. A `null` token
   multiplier likewise renders `N/A` with the unit `no cost ratio`. The server
   returns `null` when either pipeline errored (a failed run's partial tokens are
   not the cost of an answer) or the baseline spent no tokens; the summary line
   names which.

---

## 4. Configuration

Build-time environment variables (Vite `VITE_` prefix), read in
`frontend/src/config.ts`. All have defaults, so the app runs with no `.env`.
Every value is compiled into the public bundle.

| Variable | Default | Effect |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Base for every request and SSE URL |
| `VITE_API_KEY` | `''` | Sent as `X-API-Key` when non-empty. **Not a secret**: it ships in the bundle |
| `VITE_USE_MOCK_API` | `false` | **Master switch.** Only the value `true` (trimmed, case-insensitive) means mock. Anything else, including empty or a typo, means the live backend |
| `VITE_MOCK_LATENCY_SCALE` | `1` | Multiplier on every mock delay. `0` = instant (tests, screenshots) |
| `VITE_DEFAULT_RUN_ID` | `latest` | Run used when the URL has no `?run=`. `latest` or unset, on a live backend, means the newest run (§2) |
| `VITE_ADMIN_EMAIL` | `admin@example.com` | Contact address in the service gate's `mailto:` link |
| `VITE_POLL_INTERVAL_MS` | `600000` | Health polling interval |
| `VITE_LLM_HEALTH_TIMEOUT_MS` | `130000` | Browser time limit for `/health/llm`. Keep it above the backend's `HEALTH_LLM_TIMEOUT_S` |

The mock switch swaps the transport layer. Screens branch on it only for
four things:

- the `mock data` chip;
- hiding the service bar and the Settings panel (both need a live backend);
- the default-run resolution (§2);
- refusing upload and rename, which need the backend.

Every other view behaves the same against fixtures and against the real API.

---

## 5. Service layer contract

### 5.1 HTTP

- JSON request and response bodies. `Content-Type: application/json`, plus
  `X-API-Key` when a key is configured. A dataset upload sends the raw file
  instead, as `application/x-ndjson`.
- A non-2xx response becomes an `ApiError` carrying `status`, a message, and,
  when the server sends a structured `detail` (`{code, message, …}`), its
  `code` and the whole detail object. The message comes from `detail` when it
  is a string, from `detail.message` when it is an object, or from the joined
  `loc: msg` entries of a 422 validation list. Otherwise it falls back to the
  HTTP status text. A non-JSON error body must not throw; keep the status text.
- Unauthenticated routes: `GET /health`, `/health/db|llm|embedding` and
  `GET /settings`. The SSE streams use a token instead (§5.2). Everything else
  needs `X-API-Key`. When the server has no key configured, it answers `503`.

| Call | Method / path | Returns |
|---|---|---|
| Submit query | `POST /query` body `{ query, embedding_model? }` | `202 {query_id, stream_token}`. `409 embedding_mismatch` carries `selected` and `available` (§6.7) |
| Query stream | `GET /query/{query_id}/stream?token=…` | SSE |
| Query result | `GET /query/{query_id}/result` | `QueryLevelRecord`. `409` while the query is still running |
| Datasets to build | `GET /corpora` | `{corpora: Corpus[], graph: {tracked, schema, datasets}}` |
| Upload dataset | `POST /corpora/{name}?unique=true&source_file=…[&title=…]`, the body is the JSONL | `201 {name, title, title_source, documents, …}` |
| Rename dataset | `PATCH /corpora/{name}` body `{ title }` | `Corpus`. An empty title restores the inferred name |
| Start build | `POST /build` body `{ dataset, rebuild?, reset? }` | `202 {build_id, stream_token}`. `409` codes: `already_built`, `reset_required`, `build_running`, `embedding_job_running`, `batch_running`, `embedding_cap` |
| Current build | `GET /build/current` | `{build: {build_id, dataset, running, events[]} \| null}` |
| Build stream | `GET /build/{build_id}/stream?token=…` | SSE |
| Batch records | `GET /batch/{run_id}/records` | `BatchRecord[]` |
| Run history | `GET /runs` | `RunSummary[]`, newest first |
| Question sets | `GET /datasets` | `string[]` (files in `data/questions/`, including `eval_hidden`) |
| Execute benchmark | `POST /batch` body `{ dataset }` (the server also accepts `run_id`, `latency_mode`, `resume`) | `202 {run_id, status}` |
| Import run | `POST /runs/import` body `RunExport`, `BatchRecord[]` or the native JSONL parsed client-side | `201 RunSummary`. `409` if the run id exists |
| History | `GET /history` | Trials, newest first (§18) |
| Settings | `GET /settings`, `PATCH /settings`, `GET /settings/providers`, `GET /settings/models?provider=` | §19.1 |
| Embeddings | `GET /embeddings`, `GET /embeddings/plan?model=`, `POST /embeddings/switch`, `POST /embeddings/resume`, `POST /embeddings/{model}/complete` | §19.2 |
| Health | `GET /health/db`, `/health/llm`, `/health/embedding` | `{status, detail, latency_ms}` |

### 5.2 SSE

`EventSource` cannot send headers, so streams authenticate with the short-lived,
single-use `stream_token` returned alongside the id, passed as a URL-encoded
`?token=` parameter (FR-19, DP-8). Preserve this even if the new stack could
send headers — the backend contract depends on it.

Named events:

| Stream | Event | Payload | UI effect |
|---|---|---|---|
| query | `trace` | `TraceStep` | Append one step to the trace panel |
| query | `pipeline` | `PipelineRecord` | Settle that one column |
| query | `done` | — | All three settled; fetch the merged result |
| build | `build` | `BuildEvent` | Apply to every pipeline in `pipeline_affected`; a failed stage is a `build` event with `status: error` |
| build | `done` | — | Build finished |

Transport failures:

- A payload that fails to parse → the error message `Malformed {event} event`.
- Any `EventSource` error closes the stream (the token is single-use, so an
  automatic reconnect could only fail) → `Stream interrupted before the run finished`.
  The client closes the stream itself on `done`, so the server's normal close
  is never reported as an error.
- A dropped stream does not mean the run failed: the server keeps running it.
  Search recovers from `GET /query/{id}/result` (§6.2). Build follows the
  build by polling `GET /build/current` (§7.3).
- Opening a stream returns a **cancel function**. It must be called (a) before
  starting a new run and (b) on unmount. Leaking a stream across submissions is
  a real bug in this UI — a stale stream will write into the new run's columns.

### 5.3 Mock transport (must be reproduced)

The mock is not a stub; it is how the app is demoed and tested today, and how
the UI is developed with no backend.

- **Artificial latencies**, each multiplied by `mockLatencyScale`:
  submit query `120 ms`, fetch result `80 ms`, start build `120 ms`,
  fetch batch records `220 ms`.
- **Replay engine**: given timed items, schedule each at its own offset from the
  start (scaled), then fire `done` at `max(offset) + 120 ms` (scaled). Returns a
  cancel function that clears every pending timer.
- **Query replay**: `trace` events are scheduled at the **cumulative sum** of
  each step's `latency_ms`, so the trace panel fills progressively; each
  `pipeline` event is scheduled at that pipeline's own `latency_ms`, so columns
  settle at different times (this is what demonstrates FR-3 / NFR-2).
- **Scenario routing** — free text is matched to a fixture scenario by keyword,
  **most specific first**, first hit wins:

  | Scenario | Pattern (case-insensitive, word-bounded) |
  |---|---|
  | `multi_hop` | `before`, `after`, `preceding`, `immediately`, `followed` |
  | `superlative` | `most`, `fewest`, `largest`, `highest`, `biggest` |
  | `aggregation` | `how many`, `count`, `number of`, `total` |
  | `lookup` | `who`, `which nation`, `gold`, `silver`, `bronze` |
  | `default` | no match |

  Evaluation order is fixed as `multi_hop, superlative, aggregation, lookup`
  because the wordings overlap. A scenario is only returned if a fixture exists
  for it; otherwise matching continues down the order. Fixture scenarios present
  today: `aggregation`, `lookup`, `multi_hop`, `default` — there is **no**
  `superlative` fixture, so a superlative-only query keeps matching and
  typically lands on `lookup` (e.g. via `gold`), not on `default`.
- **Runs**: `latest` (20 records, scored) and `hidden` (8 records,
  `scores: null`, `ground_truth: []`). Any other id must reject with
  `No mock fixture for run "<id>" (try "latest" or "hidden")`. This error path
  is user-visible and exercised by the run picker. `services/mock/runs.ts`
  gives both a `RunSummary`. A mock benchmark (datasets `eval_public`,
  `eval_hidden`) or an import registers a new run for the session.
- **Build events**: a fixed ordered list replayed on `elapsed_ms`.
  `GET /build/current` returns nothing in mock mode. `GET /corpora` returns
  one dataset, `corpus`, titled `Wikipedia · Olympics · 1900–2022` (inferred).
- **History** is empty in mock mode. Settings, upload and rename need the
  live backend.

Fixtures live in `frontend/src/fixtures/`: `queryResults.json`,
`buildEvents.json`, `batchRecords.latest.json`, `batchRecords.hidden.json`.
**Carry these files over unchanged** — they encode the demo narrative (a
question where RAG is structurally wrong, and one where the agent spends many
times the tokens for no accuracy gain).

---

## 6. Screen — Search (`/`)

The primary screen. Vertical order: query input → verdict strip → three result
columns → agentic trace panel.

### 6.1 Query input

- One free-text field (FR-1), accessible name exactly **`Query`**, placeholder
  `Ask one question of all three pipelines`.
- Submit button labelled **`Compare`**, or **`Running…`** while a run is in
  flight. Disabled when a run is in flight **or** the trimmed value is empty.
- Submit on Enter (it is a form) and on click. The query is trimmed; empty
  submissions do nothing.
- **Example queries**: three one-click links below the field. Clicking one sets
  the input value **and immediately submits**. Disabled while running. Current
  set:
  1. `How many archery events were contested at the 2012 Summer Olympics?`
  2. `Who took gold in the men’s 100 metres in Rio?` (curly apostrophe, verbatim)
  3. `Which nation won the most gold medals in athletics at the Games immediately before the 2012 Summer Olympics?`

  These are demo-critical: they map onto the fixture scenarios and tell the
  story of the comparison. Keep all three and keep them one click.

### 6.2 Run lifecycle

On submit:
1. Cancel any previous stream.
2. Set all three columns to `running`; clear the trace; clear the previous
   merged result; clear errors; mark in-flight.
3. `POST /query` (with `embedding_model` only when re-submitted from the
   mismatch popup). On failure, return every column to `idle` and clear
   in-flight. If the refusal is `409 embedding_mismatch`, open the mismatch
   popup (§6.7). For any other error, show the error's message, else
   `Could not reach the API`.
4. Open the stream. Each `pipeline` event settles **only its own column**
   (status from `record.status`, error from `record.error_detail`). Each `trace`
   event appends a step.
5. On `done`: `GET /query/{id}/result`, render the verdict strip, then clear
   in-flight. If that fetch fails, show its message, falling back to
   `Could not load the merged result`.
6. On a stream error: recover the run from `GET /query/{id}/result`. While the
   server answers `409` (still running), poll every 3 s for up to 10 minutes.
   On success, fill every column and the verdict from the merged record. Only
   if recovery fails, show the stream's message and mark every still-running
   column `error`.

Each run has an id. A late response from a superseded run is dropped, so it
can never write into the current run's columns. Unmounting the screen cancels
the stream.

**Stop waiting.** While a run is in flight, a secondary button
`Stop waiting` sits under the query input. It cancels the stream and
supersedes the run on this page. Every still-running column becomes `error`
with the message `Stopped waiting`, and the input is re-enabled. The server
finishes the run on its own. This only stops following it.

### 6.3 Verdict strip (FR-8, FR-9)

Renders **only after all three pipelines have completed** and the merged record
has been fetched. Before that, a placeholder block reads:
`The verdict strip renders once all three pipelines have completed.`

Four metric tiles plus a summary sentence:

| Tile | Value | Label |
|---|---|---|
| 1 | `token_multiplier_vs_rag`, 2 dp, followed by `×` (`N/A` · `no cost ratio` when null) | `Agentic tokens ÷ RAG` |
| 2 | `token_multiplier_vs_graphrag`, 2 dp, `×` | `Agentic tokens ÷ GraphRAG` |
| 3 | `accuracy_delta_vs_rag` — signed, 2 dp | `Accuracy delta vs RAG` |
| 4 | `accuracy_delta_vs_graphrag` — signed, 2 dp | `Accuracy delta vs GraphRAG` |

Delta rendering: `> 0` gain tone, `< 0` loss tone, `0` neutral tone,
`'n/a'` → the literal `N/A` in a warning tone with tooltip
`No ground truth available for this query`.

`verdict.summary_line` is rendered as prose beneath the tiles, unmodified.

### 6.4 Result columns (FR-3, FR-4, FR-10, NFR-2)

Three equal columns, always in pipeline order, each rendering **independently**.
One column being `running` or `error` must never gate the others — this is the
headline resilience property and the first thing the unit tests check.

Header per column: pipeline label, the fixed subtitle from §1.1, and a status
badge.

**State `idle`** — `Submit a query to start.`

**State `running`** — two shimmer placeholder bars plus the text
`Waiting on this pipeline only — the other columns render independently.`

**State `error`** — an error block: heading `Pipeline failed`, the message
(`state.error` → `record.error_detail` → `Unknown error`), and the reassurance
`The other two columns are unaffected.`

**State `done`** — in order:

1. **Answer** — small uppercase label `Answer`, then `record.answer` as the
   largest text on the card. This is the scored span; it must be the visual
   focus of the column.
2. **Explanation** — `record.explanation`, secondary prose.
3. **Metrics row** — four tiles:
   - `tokens.total`, label `tokens`, tooltip
     `input {input} / output {output} — source: {token_source}`
   - `latency_ms` formatted, label `latency`
   - `chunks_returned`, label `chunks`
   - `citations_count`, label `citations`
4. **Token-source note** — when `token_source === 'local_tokenizer'`:
   `Token counts came from the local tokenizer — the configured provider reported no usage.`
   When `token_source === 'estimated'`:
   `Token counts are estimates (about 4 characters per token) — the provider reported no usage and the model has no tokenizer.`
   (Honesty about provenance; do not drop it.)
5. **Stop reason** — when present: label `Stopped because` + the raw
   `stop_reason` in monospace.
6. **Strategy note** — when `strategy_changed`:
   `The orchestrator deviated from its initial plan at least once.`
7. **Citations** — label `Citations`, then the list. Each entry: a `ref_type`
   tag (`chunk` / `entity` / `relationship`, colour-coded), the `source_id` in
   monospace with tooltip
   `Parent doc_id (wikidata QID) — this is the field scored against gold_doc_ids`,
   and the `chunk_id` in muted text when non-null. An entry with a `snippet` is
   a toggle button (`aria-pressed`; the snippet's first 200 characters as its
   tooltip): selecting it shows that citation's source and full snippet in a
   preview under the list, selecting it again hides it, so what was cited is
   readable on touch screens too. Empty list → `No citations returned.`
   The citation block sits at the **bottom** of the card (pushed down so the
   three columns' citation blocks align).

### 6.5 Trace panel (FR-5, FR-6, FR-7)

Always present on the search screen. Reflects the **agentic pipeline only**.

- Heading `Agentic investigation trace`, with a live summary line:
  `{n} steps` · `{total} tokens` · `{n} strategy change(s)` (singular `change`
  when exactly 1). Totals are summed over the steps received so far —
  `input + output` per step.
- Empty state: `Waiting for the first step…` while the agentic column is
  running, otherwise `No trace yet. Submit a query to watch the agent work.`
- **Ordered list of steps, appended live as each event arrives** (never
  re-rendered wholesale from a final payload — the incremental fill is the
  point). Each step shows:
  - step number badge (`step_n`)
  - agent type, title-cased (`multi_hop_reasoning` → `Multi Hop Reasoning`)
  - `tool_called` in monospace
  - a `strategy change` flag when `strategy_change` is true, and the whole step
    visually marked (warning tint / left border today)
  - `notes` as prose
  - metrics row: `{input+output} tokens` (tooltip
    `input {input} / output {output}`), latency, `{n} chunks`, `{n} citations`
- While running with at least one step: a trailing `Investigating…` line.
- Footer, when `stop_reason` is known: label `Stop reason` + the raw value in
  monospace, plus a `plan deviated` flag when `strategy_changed` is true.

The same panel is reused inside the eval table drill-down (§9.4) in a static
mode (`running: false`).

### 6.6 Console status

The query area carries a live flag. Its label is `Awaiting query` when idle,
`Synchronized run · {k}/3 settled` while running, and
`Synchronized benchmark complete` once the result lands.

### 6.7 Embedding mismatch popup

When `POST /query` answers `409` with `code: embedding_mismatch`, the selected
embedding model has no complete embeddings for the loaded data. A query never
searches another model's index, so there is no "run anyway". A modal
`alertdialog` opens (focus behaviour §20):

- Heading: `No matching embeddings for {selected.label}`.
- The server's message.
- If `available` is non-empty, the line
  `These models have complete, queryable embeddings for this data. Run the query with one of them:`
  followed by one primary button per model, `Use {label} ({dim}d)`.
  Clicking one re-submits the same query with `embedding_model` set to that
  key. The active model does not change.
- If `available` is empty: `No model has complete embeddings for this data
  yet. Build the dataset or finish a re-embed job in Settings, then query
  again.`
- `Cancel query` (or Escape) closes the popup and does nothing else.

The columns return to `idle` while the popup is open.

---

## 7. Screen — Build (`/build`)

Shows one shared ingestion build fanned out across the three pipelines. It
makes visible what each pipeline is built from:

- RAG: chunks and vectors.
- GraphRAG: the graph.
- Agentic GraphRAG: both (graph tools with vector search as a fallback).

It also shows that the pipelines become answerable at different times.
Building calls the embedding model, never an LLM.

Header: a meta line (`Pipeline ops // {phase}` and `JOB-ID: {build_id|—}`),
the heading `Ingestion build`, an explanatory paragraph, and an actions area.
The actions area holds:

- **Status flag**:
  - `Idle`
  - `Building · {overall}% · {elapsed}s`
  - `Build complete: {elapsed}s`
  - `Ready · {n} dataset(s) loaded`, after a reload with data already in the
    graph
  - `Build failed`
- **Dataset picker** (§7.4).
- **`Start build`** / `Building… {overall}%`. It is disabled while running or
  while a confirmation is pending, and gated on TigerGraph and embedding
  (§2.1).
- **`In graph:`** a line listing each loaded dataset with its document count.

### 7.1 Event application (normative reducer)

Each `BuildEvent` is applied to **every pipeline listed in
`pipeline_affected`**, and to no others. Per pipeline, the column state updates:

- `status`: `ready` is **sticky**. Once a column is `ready` it stays `ready`
  whatever events follow. Otherwise the column takes the event's status.
- `stage`: the event's stage. Once the column is `ready` (or the event is), it
  shows `ready`.
- `itemsDone` / `itemsTotal` / `elapsedMs`: overwritten from the event.
- `embedding`: taken from the `note` of a finished `embed_chunks` event (the
  model and its tier).
- **Counters**: a stage maps to at most one counter, updated with
  `max(current, items_done)` so out-of-order or partial events never regress:

  | Stage | Counter |
  |---|---|
  | `parse_infoboxes` | documents |
  | `chunk_documents` | chunks |
  | `embed_chunks` | vectors |
  | `load_vertices` | entities |
  | `load_edges` | relationships |

  Stages not in the map still drive progress and the log; they just own no
  counter.
- `log`: the event is appended.

**Percent complete** per pipeline is a weighted sum over the stages that
pipeline waits on. A finished stage counts fully. The running stage counts in
proportion to `items_done / items_total`. The result is capped at 99% until
the column is `ready` (then 100%). `remove_previous` counts only when it
appears, which happens on a rebuild. The weights:

| Stage | Weight |
|---|---|
| `embed_chunks` | 40 |
| `load_vertices`, `load_chunks`, `vector_index` | 10 each |
| every other stage | 5 |

Each pipeline waits on these stages:

| Pipeline | Stages |
|---|---|
| RAG | `chunk_documents`, `embed_chunks`, `schema_install`, `remove_previous`, `load_chunks`, `install_graph_queries`, `vector_index` |
| GraphRAG | `parse_infoboxes`, `schema_install`, `remove_previous`, `load_vertices`, `load_edges`, `install_graph_queries` |
| Agentic GraphRAG | every weighted stage; its percent is the "overall" figure |

Starting a build does four things: it resets all three columns, clears
errors, clears any pending confirmation, and cancels any previous stream.
Unmounting cancels the stream. When the start request fails without a
confirmation code, the page shows the server's message, falling back to
`Could not start the build`.

### 7.2 Column contents

Per pipeline, in order:

1. Icon, label, a percent (while active) and a status badge.
2. `Current Stage` with the stage title-cased (`Not started` when none).
3. A progress line, `{Stage}: {done} / {total} items`, or `Answerable` when
   ready, with `{pct}% complete`.
4. A progress bar (`role="progressbar"`).
5. Stat tiles. The first is `Elapsed`, or `Time to ready` once ready. The rest
   show only that pipeline's own data:
   - RAG: `Chunks`, `Vectors`.
   - GraphRAG: `Documents`, `Entities`, `Relationships`.
   - Agentic GraphRAG: `Entities`, `Relationships`, `Vectors`.
6. An embedding note. GraphRAG shows `Graph only — no embeddings, no LLM calls`.
   The others show `Embedding model: {embedding | the active model (Settings)} — no LLM calls`.
7. A disclosure, `{n} stage events`, listing the latest event per stage
   (stage, status, elapsed). It shows the note for the current stage and for
   any error. It is open while the column is active.

A `ready` column is visually distinguished: the moment a pipeline becomes
answerable is the information this screen exists to convey.

Above the columns, a **dependency flow** shows three groups:

1. `Foundation Layer`, gated on RAG.
2. `Graph Indexing`, gated on GraphRAG.
3. `Agentic Tooling`, gated on Agentic GraphRAG.

A group is `done` when its gating pipeline is ready, `failed` when that
pipeline errored, `running` once any of its stages has been seen, and
`pending` otherwise. The flow label reads `Idle`, `Stage {i}/3 in flight`,
`All stages ready` or `Failed at {Stage}`.

Below the columns, two summary panels:

- **Cumulative Ingestion Latency**: time to ready per pipeline, with the
  delta from the previous pipeline.
- **Shared Graph Store Density**: graph entities and relationships.

After a reload, with no live build but datasets already in the graph, every
column shows `ready`. The counters are totals over the loaded datasets, taken
from `GET /corpora`.

### 7.3 Failure and recovery

- **Build failure reason.** A stage that ends in `error` fails the build even
  though the stream closes cleanly. Once the build is no longer running, an
  error notice reads `Build failed at {Stage}: {note}`, where `note` comes
  from the failing event. The failing column's log also shows that note.
- **Confirmations.** A `409` with code `already_built` or `reset_required`
  opens an inline confirmation box (`role="alertdialog"`, label
  `Confirm build`) with the server's message and two buttons. `Cancel`
  appears in both cases. The other button depends on the code:

  | Code | Second button | Effect |
  |---|---|---|
  | `already_built` | `Rebuild {dataset}` | Re-sends with `rebuild: true` |
  | `reset_required` | `Reset graph and build` (danger style) | Re-sends with `reset: true`, which removes every loaded dataset |

- **Following the server.** On mount, `GET /build/current` is checked. A build
  still running on the server is replayed from its events, and the page
  follows it by polling every 2 s. If this page's own stream drops, it shows
  `Live updates were interrupted — following the build by polling.` and
  follows the same way. A failed poll is retried after 4 s.

### 7.4 Dataset picker, upload and rename

- **Picker.** A `<select>` (accessible name `Dataset`) with one option per
  file in `data/corpus/`. Each option reads
  `{display name} — {n} docs{ · built}`. The tooltip explains the JSONL
  format and that a new dataset is added alongside those already loaded. The
  picker is disabled while building.
- **Display names.** The picker shows the server's `title`, and the dataset
  id (the file stem) when no title is set. When two datasets would show the
  same name, the id is appended in parentheses. The server resolves the title
  in this order, first match wins:
  1. A title typed on upload or rename (`title_source: given`).
  2. A `dataset`, `collection` or `corpus` field the records carry
     (`declared`).
  3. A name inferred from the documents, e.g.
     `Wikipedia · Olympics · 1900–2022` (`inferred`).
  4. The file stem (`file`).
- **Upload…** is a real button that opens a hidden file input (`.jsonl`,
  `.ndjson`). Picking a file opens an inline name form:
  `Name the dataset in {file}`, with a text field of up to 80 characters, the
  placeholder `Leave empty to infer a name from its documents`, and the
  buttons `Cancel` and `Add dataset`.

  The dataset id is derived from the typed title, or else the file name, with
  unsafe characters replaced by `_`. The upload is sent with `unique=true`, so
  a taken id gets a suffix (`-2`, …) instead of failing. On success the page
  shows `Added dataset '{name}' ({n} documents)`, adds
  ` — name inferred from its documents, rename it any time` when the name was
  inferred, and selects the new dataset. On failure it shows the server's
  message (e.g. the first bad line).
- **Rename** is shown for the selected dataset. Its tooltip gives the id and
  the original file name. It opens the same form (`Rename {name}`, button
  `Save name`), prefilled only with a given title. Saving an empty title
  restores the inferred name. On success: `Dataset renamed to '{title}'.`

---

## 8. Screen — Dashboard (`/dashboard`, tab `dashboard`)

Aggregate view over exactly one batch run (FR-15, FR-20). Header: heading
`Benchmark dashboard`, the note

> Aggregate view over one batch run. Scores come from the backend scorer — no
> metric is recomputed in the browser.

and the run picker (§10.1).

**Non-negotiable invariant (NFR-5, NFR-6):** the browser **never recomputes a
score**. EM/F1/precision/recall/completeness always come from `record.scores`.
The UI only *aggregates* (mean, median, count, ratio). Do not let a redesign
introduce client-side scoring.

States: `Loading run "{runId}"…`; error box on failure; and when a run has no
scored records:
`Run "{runId}" carries no ground truth, so no accuracy metrics can be shown. Token, latency and trace aggregations below still apply.`

`scored` = records where `scores !== null`. The accuracy panels (§8.1–§8.3)
render only when `scored.length > 0`. The trace panels (§8.4) use **all**
records.

The page has a fixed panel order. The accuracy panels come first: the
headline table with the worth-it table (§8.1–§8.2), then the matrix and the
scatter (§8.3). The cost table (§8.5) follows. The trace panels come last:
the agents table (§8.6), then step counts, stop reasons and strategy changes
(§8.4).

### 8.1 Headline table

One row per pipeline (with colour swatch): mean **EM**, mean **F1**, mean
**Completeness** (2 dp), and the **median** `tokens.total` over the
pipeline's non-error answers, rounded and thousands-separated. The median,
not the mean, is used for tokens on purpose: agentic token counts are
long-tailed.

### 8.2 "Is the agent worth it, per question type?"

One row per `QType`. All five are always listed. A type with n = 0 shows `0`
and `No questions of this type in the run` across the remaining columns.

| Column | Value |
|---|---|
| Question type | title-cased |
| n | count of scored records of that type |
| `Agentic − RAG EM` | `mean(agentic EM) − mean(RAG EM)`, signed 2 dp, toned by sign |
| `Agentic ÷ RAG tokens` | mean of the **per-question ratio** `agentic.tokens.total / rag.tokens.total`, 2 dp, `×` |
| Verdict | `Worth it` if gap ≥ 0.5; else `Overkill` if gap ≤ 0.05; else `Marginal` |

The ratio is a mean of ratios, not a ratio of means. Keep it that way.
Questions with zero RAG tokens have no defined ratio and are left out.

### 8.3 Per-question-type matrix, and the scatter

- **Matrix**: rows = five metrics (`EM`, `F1`, `Recall`, `Precision`,
  `Completeness`); columns = five question types × three pipelines (abbreviated
  `RAG` / `GR` / `AG`, each with its colour swatch), a two-row header with each
  qtype spanning its three pipeline columns. Cells are the mean over that
  (qtype, pipeline), 2 dp, or `—` when no rows. Horizontally scrollable.
  Footnote: `Completeness` carries a `*` and the note
  `* Completeness is an explicit alias of Recall — |retrieved ∩ gold| / |gold| — kept because the guidebook names the column.`
- **Scatter — "Accuracy against tokens"**: x = `tokens.total`, y = `F1`
  (fixed 0–1 axis), one series per pipeline in its colour, one point per scored
  question. Each point needs a hover readout:
  `{pipeline} — {qid} ({qtype})`, then the x and y values. Legend below.
  This chart is the visual thesis of the whole project: cost on x, accuracy on
  y. Keep it, keep it labelled, keep the per-point tooltip.

### 8.4 Trace aggregations (rendered for every run, scored or not)

- **Agentic step-count distribution** — horizontal bars, one per distinct trace
  length, labelled `{n} steps`, ascending by step count, value = number of
  questions. A record with a null trace counts as 0 steps.
- **Stop-reason breakdown** — horizontal bars, one per distinct `stop_reason`
  (null → `none`), **sorted by count descending**.
- **Strategy changes** — three tiles: number of runs that deviated, total steps
  flagged, and the percentage `changed / total` (or `—` when there are no runs)
  labelled `of {n} runs`.

### 8.5 Cost, latency and reliability (rendered for every run, scored or not)

One row per pipeline, with a colour swatch, over **all** records:

| Column | Value |
|---|---|
| Answered | records whose status is not `error` |
| Errors | error records (loss tone when > 0) |
| Median tokens | median `tokens.total` over answered |
| Mean input / Mean output | mean `tokens.input` / `tokens.output` over answered, rounded |
| Mean latency | mean `latency_ms` over answered, as `{s, 1 dp} s` |
| Mean citations | mean `citations_count` over answered, 2 dp |
| Grounded | mean `grounding[pipeline]` over answered questions, 2 dp; `—` when the run carries none. Needs no ground truth |

Footnote: `Over answered questions; errored answers are counted, not averaged in.`
An errored answer must never enter a mean as a zero-token answer. A record
missing a pipeline (for example, from an imported run) is skipped for that
pipeline.

### 8.6 Agentic trace: agents invoked

Rendered when any agentic trace step exists. One row per `agent_type` across
every record's agentic trace, sorted by invocations, descending:

| Column | Value |
|---|---|
| Agent | title-cased |
| Invocations | step count |
| Tokens | Σ `input + output` |
| Tokens / call | tokens ÷ invocations |
| Time / call | Σ `latency_ms` ÷ invocations |

---

## 9. Screen — Eval table (`/dashboard?tab=eval`; `/eval` redirects here)

Per-question results for every question in the run across all three pipelines
(FR-20). Header: heading `Per-question results` and a live sentence:
`Every question in the run against all three pipelines. {d} of {n} questions have the pipelines disagreeing — that filter is where the research question lives.`
Plus the run picker.

### 9.1 Filters

Four controls, all client-side, composable:

| Control | Options | Effect |
|---|---|---|
| Question type | `All` + five qtypes | Filters rows |
| Pipeline | `All three` + each pipeline | Restricts **which column groups render** (not which rows) |
| Sort by | `Question id` (default), `Question type`, `Agentic − RAG EM`, `Agentic tokens` | Row order |
| Pipelines disagree only | checkbox | Filters rows to disagreements |

Sort semantics: by qid — lexicographic ascending; by qtype — qtype then qid; by
EM gap — `agentic.em − rag.em` **descending** (0 when unscored, and the option is
**disabled** when the run has no gold); by tokens — agentic `tokens.total`
descending.

### 9.2 Disagreement detection

A row "disagrees" when the three pipelines' answers are not all equal after
SQuAD-style normalization: lowercase → curly apostrophes to `'` → strip articles
(`a`, `an`, `the`) → replace non-word/non-apostrophe characters with spaces →
collapse whitespace → trim. This normalization exists **only** to decide
disagreement; it must never be used to score anything (scoring is the backend's
single implementation).

### 9.3 Table

Two-row header. Fixed first column `Question` (row-spanning), then `Gold` (only
when the run has gold), then one column group per shown pipeline with its
colour swatch and label.

Sub-columns per pipeline group:
- with gold (7): `Answer`, `EM`, `F1`, `P`, `R`, `Tokens`, `Latency`
- without gold (4): `Answer`, `Cites`, `Tokens`, `Latency`

When the run has no gold, show the note
`Run "{runId}" supplies no gold answers, so the gold and score columns are hidden.`

Cell contents:
- **Question cell**: `qid` in monospace, a question-type tag, and the question
  text.
- **Gold cell**: the `ground_truth` variants joined with ` / ` in bold, and the
  `gold_doc_ids` joined with `, ` beneath in muted small text.
- **Answer cell**: `record.answer`; for the agentic pipeline additionally
  `{n} steps · {stop_reason ?? '—'}` on its own line.
- **EM** is toned: 1 = gain, 0 = loss. F1/P/R to 2 dp. Tokens
  thousands-separated. Latency formatted.
- Table scrolls horizontally; numeric cells are right-aligned and
  tabular-figured, text cells left-aligned.

### 9.4 Row drill-down

Clicking a row expands it (one row open at a time; clicking the open row
collapses it). The open row is visually highlighted. The expanded panel spans
the full table width and contains two areas side by side (stacked on narrow
screens):

1. **Retrieved document sets** — for **all three pipelines regardless of the
   pipeline filter**, the label and the comma-joined `citations[].source_id`
   (or `—` when empty); plus, when gold exists, a `Gold` row with
   `gold_doc_ids` in the gain colour so retrieval hits are eyeballable. Below
   them, `record.verdict.summary_line`.
2. **The trace panel** (§6.5) for that question's agentic run, in static mode,
   with its stop reason and strategy flag.

When filters match nothing: `No questions match these filters.`

---

## 10. Shared components

### 10.1 Run picker

A small form: the label `Run`, a free-text input and a `Load` button. The
input follows the current run id, including back/forward navigation and the
newest-run resolution. Submitting sets `?run=<value>`, trimmed; an empty
value does nothing. Both Dashboard and Eval table use it, and `?tab=` is kept.
Browsing and choosing runs is the Run benchmark tab's job (§10.4). That tab
links into both views with `?run=`. Known mock ids: `latest`, `hidden`.

### 10.2 Status badge

Statuses `idle` / `running` / `done` / `error` / `ready` → labels `Idle` /
`Running` / `Done` / `Error` / `Ready`. `running` additionally shows a pulsing
indicator. Each status is colour-coded (§12). The literal label text is asserted
in the tests.

### 10.3 Charts

Two chart primitives today, both dependency-free (no chart library):

- **BarChart** — horizontal; label column / track / value column; one colour for
  the whole series; bars scaled to `max(values, 1)`. Empty → `No data.`
- **ScatterPlot** — multi-series, 640×300 viewBox, padding
  `{top 16, right 16, bottom 44, left 52}`; x scaled to `1.05 × max(x)`; y fixed
  0–1; y gridlines and ticks at `0, .25, .5, .75, 1`; x ticks at the same
  fractions of the max, rounded to hundreds (below a max of 400: to the
  largest power of ten <= max/4), duplicates dropped; points r=5 at 70% fill opacity,
  each with a hover title; axis labels on both axes; legend of series swatches.
  Empty → `No data.`

Every ScatterPlot also has a `<details>` "Show data table" fallback (§14).

A redesign may swap in a chart library, provided the **data, axes, tooltips,
legend, per-pipeline colours and theme-responsiveness** survive. Note that CSS
`var()` colours only resolve in CSS, so SVG series colours are applied via
`style`, not the `fill`/`stroke` attributes — keep that or the dark/light switch
will silently stop applying to the charts.

### 10.4 Run benchmark tab (`/dashboard?tab=runs`)

Heading `Runs & history`, plus a sentence explaining that every execution is
kept with its model, dataset and embedding metadata, and that selecting two
or more runs compares them against the first one selected.

- **Actions**:
  - a `Dataset` select, filled from `GET /datasets`. It defaults to
    `eval_public`, else the first set not named `hidden`/`holdout`: the hidden
    set is run once, deliberately, and sorts first;
  - `Run benchmark`, which calls `POST /batch {dataset}` and is gated on all
    three services (§2.1);
  - `Import JSON`, which accepts a `.json` export, a bare record list, or the
    native `.jsonl` run file whose first line is the `run_config` header.

  Results show in a closable notice: `Benchmark {id} started on {dataset}.`,
  `Imported {id} ({n} questions).` or the error.
- **Tiles**: runs in history, the best agentic F1 (with its run), the best
  agentic F1 per 1k tokens (with its run), and `tokens spent, all runs`.
- **History table**: filterable by run, model, dataset or embeddings. Each row
  has:
  - a compare checkbox;
  - the run id with its start time, and a status badge when the run is not
    complete (`running` / `failed`, with the error when failed);
  - the dataset;
  - `Model · embeddings`;
  - `n`;
  - F1 per pipeline;
  - agentic median tokens and F1 per 1k tokens;
  - the links `Dashboard` (`?tab=dashboard&run=`) and `Eval` (`?tab=eval&run=`);
  - `Export`, which downloads `{run_id}.json` as a `RunExport`.

  While any run is `running`, the list is polled every 3 s.
- **Scatter**: accuracy against cost. One point per run and pipeline, with x =
  median tokens and y = mean F1. It covers the selected runs, or every scored
  run when none is selected.
- **Compare** (two or more selected): a configuration table covering provider,
  model, embeddings, dataset, k, chunk tokens, max steps, token budget,
  temperature, seed, latency mode and pool size. Differing values are marked.
  Below it, a metric table (EM, F1, Precision, Recall, Median tokens, Mean
  latency, F1 per 1k tokens, Errors) per pipeline, with deltas against the
  first run selected. `Clear selection` resets it.

Resuming an unfinished run is available from the CLI and the API
(`resume: true`), not from this tab.

---

## 11. Formatting rules (normative)

Shared helpers; identical output is expected wherever a value of that kind is
displayed.

| Helper | Rule | Example |
|---|---|---|
| `num(n)` | `en-US` thousands separators | `18430` → `18,430` |
| `ms(n)` | `< 1000` → rounded `"{n} ms"`; else `"{n/1000, 2dp} s"` | `1820` → `1.82 s` |
| `dec(n, 2)` | fixed decimals | `0.6` → `0.60` |
| `signed(n, 2)` | fixed decimals with an explicit `+` when positive | `0.35` → `+0.35` |
| `titleCase(s)` | `_` → space, capitalise each word | `multi_hop` → `Multi Hop` |
| `mean(xs)` | arithmetic mean; `0` for empty | |
| `median(xs)` | median of a sorted copy; average of the two middles for even length; `0` for empty | |

`pct(n)` (`0.5` → `50%`) exists in the helpers but is currently unused — the
dashboard percentages are computed inline. Either wire it up or drop it in the
rewrite; don't leave two rounding behaviours.

Presentation rules that matter: metric values and table numerals use tabular
figures so columns align; scores are always 2 dp on a 0–1 scale (never converted
to percentages); token multipliers are 2 dp followed by `×`.

---

## 12. Theming and colour semantics

Design is being redone, so treat the hex values as a *starting point*; treat the
**token names and their semantics** as the contract, because components, charts
and SVG all reference them.

| Token | Meaning | Dark | Light |
|---|---|---|---|
| `--bg` | page background | `#0d1117` | `#f6f8fa` |
| `--bg-raised` | cards, header | `#161b22` | `#ffffff` |
| `--bg-sunken` | inputs, tiles, table head | `#010409` | `#eff2f5` |
| `--border` | all hairlines | `#30363d` | `#d1d9e0` |
| `--text` / `--text-muted` | body / secondary | `#e6edf3` / `#8b949e` | `#1f2328` / `#59636e` |
| `--accent` | interactive, links, progress | `#58a6ff` | `#0969da` |
| `--accent-contrast` | text on accent | `#05204a` | `#ffffff` |
| `--rag` | **RAG identity** | `#f0883e` | `#bc4c00` |
| `--graphrag` | **GraphRAG identity** | `#58a6ff` | `#0969da` |
| `--agentic` | **Agentic identity** | `#7ee787` | `#1a7f37` |
| `--gain` / `--loss` | positive / negative delta | `#7ee787` / `#ff7b72` | `#1a7f37` / `#cf222e` |
| `--warn` | N/A values, strategy changes, mock flag | `#d29922` | `#9a6700` |
| `--gain-bg`, `--loss-bg`, `--warn-bg`, `--accent-bg`, `--accent-bg-strong` | tinted surfaces | | |

Semantic rules to preserve:

- Each pipeline's identity colour is used for: its column's top edge, its table
  swatches, its chart series, and the matching citation `ref_type` tag
  (`chunk` → RAG colour, `entity` → GraphRAG colour, `relationship` → Agentic
  colour).
- GraphRAG's identity colour equals the accent colour today; if the new design
  separates them, check nothing depended on them matching.
- Positive/negative deltas must be distinguishable **without colour alone** —
  the explicit `+`/`−` sign carries it today; keep it.

### 12.1 Theme switching (must be preserved)

- Two themes, `light` and `dark`, applied as `data-theme` on the document root.
- Initial value: stored choice, else the OS preference
  (`prefers-color-scheme: light` → light, otherwise dark).
- Persisted to `localStorage` under the key **`ogr-theme`**. Every read and
  write is wrapped in try/catch — in a private window or with site data blocked
  the toggle must still work for the session.
- The same resolution runs in a **blocking inline script before first paint**, so
  a light-mode user never sees a dark flash. Reproduce this in the new stack.
- `color-scheme` is declared per theme so native controls and scrollbars follow.

---

## 13. Responsive behaviour

- Single breakpoint today at **1100px**: the three-column grids (search results,
  build columns) collapse to one column, and the eval drill-down goes from two
  columns to stacked.
- The dashboard panel grid is intrinsically responsive (auto-fit, min 300px).
- Wide tables (per-question-type matrix, eval table) scroll horizontally inside
  their container rather than shrinking — the eval table reaches 23 columns and
  must not be compressed into unreadability.
- Content is capped at 1600px and centred.

A redesign may add breakpoints freely. The requirement is: **the three pipelines
must be comparable at a glance on a desktop viewport**, since side-by-side
comparison is the product.

---

## 14. Accessibility requirements

Present today, to be kept or improved:

- The query field has an accessible name of exactly `Query`.
- The theme toggle has an `aria-label` naming the target mode.
- Decorative icons are `aria-hidden`.
- The scatter SVG has `role="img"` and an `aria-label` of the form
  `{yLabel} against {xLabel}`.
- Tables use real `<th>` elements with `scope="row"` on row headers and
  `colSpan`/`rowSpan` for the grouped headers.
- Form controls are associated with labels (the run picker uses `htmlFor`).

Also implemented, and to be kept in any rebuild:

- Expandable eval rows are focusable (`tabIndex=0`), toggle on Enter/Space
  (Space's default prevented), carry `aria-expanded`, and while open point
  `aria-controls` at the drill-down row (`id="eval-detail-{qid}"`).
- Search view has a visually hidden `role="status"` `aria-live="polite"`
  region: `"{k} of 3 pipelines complete, {n} trace step(s)."` while running,
  `"All three pipelines complete. Verdict ready."` once the result lands,
  empty otherwise.
- Every ScatterPlot has a `<details>` "Show data table" fallback listing
  Series, Point, x and y for each plotted point. BarChart already prints its
  values as text.
- The Dashboard tabs are a `role="tablist"` with `aria-selected` and
  `aria-controls`, and the panel is a `role="tabpanel"`.
- History rows are keyboard-expandable, the same way as eval rows.
- Build progress bars are `role="progressbar"` with `aria-valuenow`.
- Modal dialogs follow §20.

---

## 15. Contract to preserve (checklist for the rebuild)

Behaviour, not pixels. Each line maps to something a user or a test depends on.

**Global**
- [ ] Four routes (Search, Build, Dashboard, History) + two redirects + not-found, with `/` as the search screen
- [ ] `/benchmarks` and `/eval` redirect to their Dashboard tabs, keeping `?run=`
- [ ] `?run=` drives Dashboard and Eval table, and is written by the run picker; without it a live backend opens the newest run
- [ ] Service indicators and service gates in live mode
- [ ] `mock data` chip appears whenever the mock transport is active
- [ ] Theme toggle, OS default, `ogr-theme` persistence, no flash of wrong theme
- [ ] All API/mock behaviour behind one switch, off unless exactly `true`
- [ ] Modal dialogs: focus in, Tab trapped, Escape closes the top dialog only, focus restored (§20)

**Search**
- [ ] One field, `Compare` button, Enter-to-submit, disabled while running
- [ ] Three one-click example queries that set **and** submit
- [ ] Three columns render independently; one done while others run (FR-3)
- [ ] One pipeline failing leaves the other two intact, with the reassurance copy (NFR-2)
- [ ] Answer shown as the prominent value, separate from the explanation (FR-17)
- [ ] Tokens / latency / chunks / citations per column, with the input-output tooltip (FR-4)
- [ ] `local_tokenizer` provenance note when applicable
- [ ] Citations listed with ref-type, `source_id` and optional `chunk_id` (FR-10)
- [ ] Trace steps appended live, one at a time (FR-5)
- [ ] Strategy changes flagged on the step and in the summary (FR-6)
- [ ] Stop reason displayed in the column and the trace footer (FR-7)
- [ ] Verdict strip only after all three complete; placeholder before (FR-8)
- [ ] `N/A` shown, not omitted, when no ground truth (FR-9)
- [ ] Previous stream cancelled on re-submit and on unmount
- [ ] A dropped stream is recovered from the stored result
- [ ] `Stop waiting` stops following a run without affecting the server
- [ ] Embedding mismatch popup offers only complete models; no "run anyway"

**Build**
- [ ] One build, fanned out to the pipelines each stage affects
- [ ] `ready` is sticky per column, and a ready column is visually distinct
- [ ] Counters advance monotonically via `max`; tokens accumulate
- [ ] Progress bar, `done / total items`, elapsed, five counters
- [ ] Full stage log per pipeline in a disclosure
- [ ] Dataset picker, upload with an optional name, rename; inferred names
- [ ] Rebuild / Reset confirmations for `already_built` / `reset_required`
- [ ] Failure notice naming the failed stage and its reason
- [ ] A running server build is followed after a reload or a dropped stream

**Dashboard**
- [ ] No score is ever recomputed in the browser
- [ ] Headline: mean EM, mean F1, **median** tokens per pipeline
- [ ] Worth-it table with the 0.5 / 0.05 thresholds and mean-of-ratios
- [ ] 5 metrics × 5 qtypes × 3 pipelines matrix, `—` for empty cells
- [ ] Completeness footnoted as an alias of Recall
- [ ] F1-against-tokens scatter with per-point tooltips and a legend
- [ ] Step-count distribution, stop-reason breakdown (desc), strategy-change tiles
- [ ] A run with `scores: null` hides accuracy, keeps the rest, and says why
- [ ] Cost, latency and reliability table; errored answers counted, not averaged in
- [ ] Agentic trace: agents invoked table
- [ ] Run benchmark tab: run, history, import/export, compare

**Eval table**
- [ ] Every question × three pipelines in one table
- [ ] Disagreement count in the header and a disagree-only filter (FR-20)
- [ ] Normalization used for disagreement only, never for scoring
- [ ] qtype filter, pipeline filter, four sorts, EM-gap sort disabled without gold
- [ ] Gold and score columns hidden with a note when the run has no gold
- [ ] Row drill-down: retrieved doc sets for **all three** pipelines, gold set, verdict line, full trace
- [ ] One row open at a time
- [ ] Empty-filter message

**History and Settings**
- [ ] History lists every attempt with type/status filters, search and a raw-record expansion
- [ ] Settings: provider presets (unconfigured ones disabled), model filter, custom id, auto-close 10 s after Apply
- [ ] Embedding switching: model states, a two-option decision dialog with nothing preselected, mandatory eviction at the cap, job status with Resume/Complete, disabled while a build/job/benchmark runs

**Cross-cutting**
- [ ] Pipeline order `rag → graphrag → agentic_graphrag` everywhere
- [ ] Pipeline identity colours consistent across columns, tables, charts, ref-type tags
- [ ] Formatting helpers applied uniformly (§11)
- [ ] Loading, empty, error and partial states for every data-backed view

---

## 16. Test hooks that currently exist

The component tests (`frontend/src/*.test.tsx`, `components/*.test.tsx`,
`services/*.test.ts`) drive the UI through these handles, among others. If the rebuild changes them, update the tests deliberately —
don't discover it by breakage.

| Handle | Used for |
|---|---|
| `aria-label="Query"` on the input | typing a query |
| Button named `Compare` | submitting |
| `data-pipeline="{id}"` on each result column | locating a column |
| `data-status="{idle\|running\|done\|error}"` on each column | asserting per-column state |
| Badge text `Running` / `Done` / `Error` / `Idle` / `Ready` | asserting status |
| Trace summary text `{n} steps` | asserting incremental trace fill |
| Verdict placeholder copy | asserting the strip waits for all three |

Carrying `data-pipeline` / `data-status` into the new markup is the cheapest way
to keep the existing tests meaningful.

---

## 17. Current stack (reference only)

React 18 + TypeScript + Vite, `react-router-dom` v7, hand-written CSS with
custom properties, no UI or chart library, and no state manager (local
`useState` plus `useSearchParams`). Tests use Vitest + Testing Library
(jsdom).

None of this is binding on the rebuild. What is binding is everything else in
this document, including §18–§20 below.

---

## 18. Screen — History (`/history`)

A list of every attempt the backend records in `out/history.jsonl`
(`GET /history`, newest first). It includes queries, builds, benchmarks and
embedding jobs, whether they succeeded, failed, were refused, or are waiting
on a rebuild decision (`needs_confirmation`).

- Header: the heading `History`, a one-line explanation, and a `Refresh`
  button.
- Filters (client-side, composable):
  - `Type`: All / Query / Build / Benchmark;
  - `Status`: All, plus every status present, title-cased;
  - a search box matching the subject, the model, the provider, the dataset
    and the error.

  A counter reads `{shown} of {total}`.
- Table columns: `When` (local time), `Type`, `Status` (a badge),
  `Query / dataset` (the subject, with the error beneath in error text),
  `Model` (`provider/model`), `Duration`, `Tokens`.
- Badge tones:
  - `done`, `ready` and `complete` use the done tone;
  - `partial` and `needs_confirmation` use the running tone;
  - every other status uses the error tone.
- A row toggles on click, Enter or Space (`tabIndex=0`, `aria-expanded`). It
  expands to the raw trial as pretty-printed JSON.
- States: `Loading…`, a closable error notice, and
  `No attempts recorded yet.` Mock mode always shows an empty history.

---

## 19. Settings panel

Opened from the header's gear button. It is live mode only; in mock mode the
button is not rendered. The panel is a modal dialog (`role="dialog"`,
`aria-modal`, titled `Settings`) with a close button (`✕`). Clicking the
backdrop closes it, as does Escape. Focus behaviour is described in §20.

### 19.1 LLM provider and model

On open, the panel loads `GET /settings` (unauthenticated) and
`GET /settings/providers`. While loading it shows
`Loading current configuration…`.

- **Provider** select. The options are the presets `Google Gemini (AI
  Studio)`, `NVIDIA NIM` and `Groq`.
  - A preset whose API key is not set on the server is **disabled**, with
    the suffix ` — API key not set`.
  - The preset currently serving the model stays selectable even without its
    preset key (suffix ` — server default key`).
  - When the startup provider is none of the presets, an extra option shows it
    as `{provider} · {host} (server default)`.
- **Model** (`Intelligent Engine · Model`):
  - For a preset, the panel loads the provider's live catalog
    (`GET /settings/models`). NVIDIA's list is narrowed to free endpoints; a
    `note` explains when that was not possible.
  - A search box filters the list by name, case-insensitive substring match.
    Its placeholder is `Filter {n} models by name…`. When the filter matches
    nothing, the panel shows `No model matches “{filter}”.`
  - Models are radio cards.
  - Without a catalog, the panel shows `Loading models…`, the error, or
    `No model list for this provider — enter a model ID.`
  - A `Custom model ID` text field overrides the selection.
  - A current model that is not in the list is noted as `(custom)`.
  - A catalog that arrives late, after the provider has changed, is ignored.
- **Apply** (`Saving…` while in flight) sends `PATCH /settings` with only what
  changed. The provider is sent only if it changed; the model is sent if it or
  the provider changed.
  - On success, the panel shows `Saved — all pipelines now use {label} /
    {model}`, triggers a health re-check, and starts an **auto-close
    countdown**: `Closing in {n}s · Keep open`, from 10 s. Any edit inside the
    panel, `Keep open`, or dismissing the notice cancels the countdown. At 0,
    the panel closes.
  - On failure, the panel shows the server's message (e.g. `GROQ_API_KEY is
    not set on the server`) and stays open.
- **Cancel** closes the panel without saving.

The embedding model is **never** changed by Apply. It has its own flow
(§19.2).

### 19.2 Embedding model switching

A fieldset, `Knowledge Base · Embedding Model`, loaded from `GET /embeddings`
(see `EMBEDDING-SWITCHING.md`). Every refusal shown here is also enforced by
the server.

- **Summary line**: `{stored}/{cap} models stored for {n} chunks. A query only
  ever searches its own model's embeddings.` The cap is 2.
- **Old layout note**: when the graph still uses the old one-vector-per-chunk
  layout, a note says to run a build with a reset.
- **Model cards**: one radio card per model, showing its label, its dimension
  (`{dim}d`) and its state. The active model is prefixed `Active · `. The
  states:

  | State | Label |
  |---|---|
  | `complete` | `Complete` |
  | `incomplete` | `Incomplete · {done}/{total} chunks` |
  | `building` | `Building · {done}/{total}` |
  | `failed` | `Failed · resumable` |
  | `evicting` | `Being removed` |
  | `indexing` | `Indexing · Complete to finish` (written, but the vector index is not yet confirmed queryable) |
  | `not_stored` | `Not stored` |

  An `incomplete` or `indexing` model that is not the current job's model has
  a `Complete` button (`POST /embeddings/{model}/complete`).
- **Job status** (`role="status"`), shown while a job exists and is not
  complete. It reads `{model}: re-embedding — {phase}.`, where the phase is
  one of:
  - `starting`;
  - `removing {models}`;
  - `batch {i}/{n} · {done}/{total} chunks`;
  - `waiting for the vector index`.

  A failed job reads `{model}: failed while {phase} — {error}. Resume
  continues from the last finished batch.` and has a `Resume` button
  (`POST /embeddings/resume`).
- **Polling**: every 3 s while a job is running or a build is running.
- **Disabled while busy**: when a build, a re-embed job or a benchmark run is
  in progress, the server sends a `switch_disabled_reason`. The whole fieldset
  is then disabled with `Switching is disabled: {reason}` and a note that it
  re-enables when the build or job ends. The fieldset is also disabled while a
  request of its own is in flight.
- **Choosing a model** fetches `GET /embeddings/plan?model=` and opens the
  **decision dialog** (a modal `role="dialog"`, §20):
  - Title `Switch embeddings to {label}`, then a cap line:
    `{stored}/{cap} models currently stored: {list}. {label} is {dim}-dim,
    {state}.`
  - **Instant case** (the target is already complete): one sentence, then
    `Switch`.
  - Otherwise, **two options, neither preselected**, each with pros and cons
    computed from the real state:
    1. **Force full re-embed** (`replace`). Pro: no extra storage, because the
       outgoing model's embeddings are deleted first (any other stored model
       is kept). Con: blocking, because queries with the new model wait until
       every chunk is embedded. Con: no quick fallback to the deleted model.
    2. **Keep parallel indices** (`parallel`). Pro: the current model stays
       queryable while the new one builds, and switching back is instant. Con:
       extra TigerGraph storage and one more HNSW index. Con: capped at 2
       models.
  - **Mandatory eviction at the cap**: when the chosen option would exceed the
    cap, an `Evict one model first (required)` fieldset lists the evictable
    models, with the active one marked
    `(active — queries then wait for the new model)`. The eviction runs before
    the new model is embedded, and deletes only that model's embeddings, index
    and edges.
  - The confirm button reads `Choose an option`, `Re-embed` or
    `Build alongside`. It is disabled until an option (and, where required,
    an eviction) is chosen.
  - `Cancel` or Escape closes only this dialog; the Settings panel stays open.
  - A refusal shows inside the dialog, and the state is refreshed.

---

## 20. Dialog focus behaviour

Every modal dialog uses one hook (`components/useDialogFocus.ts`). That covers
the Settings panel, the embedding decision dialog and the embedding mismatch
popup. The hook does four things:

- **Focus moves in** on open, to the first focusable element (or the dialog
  itself).
- **Tab is trapped**: Tab from the last element goes to the first, and
  Shift+Tab from the first goes to the last.
- **Escape closes the top dialog only**. A nested dialog's Escape stops
  propagation, so the Settings panel underneath the embedding dialog stays
  open.
- **Focus returns** to the previously focused element on close.

The Build screen's confirmation box and name form are inline, not modal. The
name form autofocuses its field.
