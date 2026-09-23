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

Client-side routing, five screens plus a not-found:

| Route | Screen | Purpose |
|---|---|---|
| `/` | **Search** (compare) | Ask one question, watch three pipelines answer live |
| `/build` | **Build** | Run the ingestion build, watch each pipeline become answerable |
| `/dashboard` | **Dashboard** | Aggregate benchmark over one batch run |
| `/eval` | **Eval table** | Per-question results for one batch run, with drill-down |
| `/benchmarks` | **Benchmarks** | Run history: execute, import/export and compare benchmark runs |
| anything else | Not found | Renders the text `Not found.` |

`/dashboard` and `/eval` read the run id from the query string: `?run=<run_id>`.
This must stay a URL parameter — those views are meant to be linkable. When
absent, the run id falls back to `VITE_DEFAULT_RUN_ID` (default `latest`).

### 2.1 App shell

Persistent header above the routed view:

- **Brand**: title `Agentic GraphRAG`, muted subtitle `Three-pipeline comparison`.
- **Nav**: `Search` (exact match on `/`), `Build`, `Dashboard`, `Eval table`.
  The active route must be visually distinct.
- **Mock-data flag** (right side, **only when `useMockApi` is true**): a chip
  reading `mock data`, tooltip
  `VITE_USE_MOCK_API=true — every screen is served from src/fixtures`.
  This is a correctness feature, not decoration: it stops anyone reading fixture
  numbers as real results. It must remain visible and unmissable.
- **Theme toggle** (right side): sun icon when in dark mode, moon icon when in
  light. `aria-label` and `title` both read `Switch to {light|dark} mode`
  (naming the *target* mode).

Header is sticky at the top of the viewport today; the content area is
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
  | 'entity_linking' | 'graph_traversal' | 'similarity_search'
  | 'document_retrieval' | 'aggregation' | 'multi_hop_reasoning'
  | 'evidence_evaluation'

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
  token_multiplier_vs_rag: number
  token_multiplier_vs_graphrag: number
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
  qtype: QType
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
  tokens: number               // always 0 — ingestion uses a local encoder
  note: string
}

interface QueryAccepted { query_id: string; stream_token: string }
interface BuildAccepted { build_id: string; stream_token: string }
```

Two nullability rules drive whole screens and are easy to lose in a rewrite:

1. **`scores === null`** (a hidden/holdout run) → every accuracy column, table
   and chart disappears; token/latency/trace aggregations still render, with an
   explanatory note. Never render `0` or `—` in place of an absent score without
   the note.
2. **`accuracy_delta_* === 'n/a'`** → the verdict strip shows `N/A` in a warning
   tone **and keeps the field** (FR-9). Do not omit the tile.

---

## 4. Configuration

Build-time environment variables (Vite `VITE_` prefix today). All have defaults,
so the app runs with no `.env`.

| Variable | Default | Effect |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Base for every request and SSE URL |
| `VITE_API_KEY` | `''` | Sent as `X-API-Key` on every request when non-empty |
| `VITE_USE_MOCK_API` | `true` | **Master switch.** Any value other than `false` (case-insensitive) means mock |
| `VITE_MOCK_LATENCY_SCALE` | `1` | Multiplier on every mock delay; `0` = instant (tests, screenshots) |
| `VITE_DEFAULT_RUN_ID` | `latest` | Run id used when the URL has no `?run=` |

The mock switch must remain a single flag that swaps the transport layer only —
**no screen may branch on it** beyond showing the `mock data` chip. Every view
must work identically against fixtures and against the real API.

---

## 5. Service layer contract

### 5.1 HTTP

- JSON request/response. `Content-Type: application/json`; `X-API-Key` when a
  key is configured.
- Non-2xx → error carrying `status` and a message taken from the response body's
  `detail` field, falling back to the HTTP status text. A non-JSON error body
  must not throw; keep the status text.

| Call | Method / path | Returns |
|---|---|---|
| Submit query | `POST /query` body `{ query }` | `202 {query_id, stream_token}` |
| Query stream | `GET /query/{query_id}/stream?token=…` | SSE |
| Query result | `GET /query/{query_id}/result` | `QueryLevelRecord` |
| Start build | `POST /build` body `{}` | `202 {build_id, stream_token}` |
| Build stream | `GET /build/{build_id}/stream?token=…` | SSE |
| Batch records | `GET /batch/{run_id}/records` | `BatchRecord[]` |
| Run history | `GET /runs` | `RunSummary[]` (newest first) |
| Datasets | `GET /datasets` | `string[]` |
| Execute benchmark | `POST /batch` body `{ dataset }` (server also accepts optional `run_id`, `latency_mode`) | `202 {run_id, status}` |
| Import run | `POST /runs/import` body `RunExport` or `BatchRecord[]` | `201 RunSummary` |

The run picker on Dashboard and Eval table stays a free-text field (§10.1);
browsing and choosing runs is the Benchmarks screen's job, which links into
both with `?run=`.

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
| query | `error` | `{detail?}` | Show submit error; stop the in-flight state |
| build | `build` | `BuildEvent` | Apply to every pipeline in `pipeline_affected` |
| build | `done` | — | Build finished |
| build | `error` | `{detail?}` | Show error; stop running state |

Transport failures:

- Payload that fails to parse → error message `Malformed {event} event`.
- Socket closes unexpectedly (`readyState === CLOSED`) → `Stream closed unexpectedly`.
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
  `No mock fixture for run "<id>" (try "latest" or "hidden")` — this error path
  is user-visible and exercised by the run picker.
- **Build events**: a fixed ordered list replayed on `elapsed_ms`.

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
3. `POST /query`. On failure: show the error, return every column to `idle`,
   clear in-flight. Message = the error's message, else `Could not reach the API`.
4. Open the stream. Each `pipeline` event settles **only its own column**
   (status from `record.status`, error from `record.error_detail`). Each `trace`
   event appends a step.
5. On `done`: clear in-flight, then `GET /query/{id}/result` and render the
   verdict strip. If that fetch fails, show `Could not load the merged result`.
6. On stream `error`: clear in-flight and show the message.

Unmounting the screen cancels the stream.

### 6.3 Verdict strip (FR-8, FR-9)

Renders **only after all three pipelines have completed** and the merged record
has been fetched. Before that, a placeholder block reads:
`The verdict strip renders once all three pipelines have completed.`

Four metric tiles plus a summary sentence:

| Tile | Value | Label |
|---|---|---|
| 1 | `token_multiplier_vs_rag`, 2 dp, followed by `×` | `Agentic tokens ÷ RAG` |
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
   and the `chunk_id` in muted text when non-null. Empty list →
   `No citations returned.`
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

---

## 7. Screen — Build (`/build`)

Shows one shared ingestion build fanned out across the three pipelines, making
visible that **RAG consumes the shared foundation while GraphRAG and Agentic pay
for the graph**, and that the pipelines become answerable at different times.

Header: heading `Ingestion build`, the explanatory paragraph

> One shared build. Each column shows when that pipeline becomes answerable,
> fanned out by the stages it depends on — RAG consumes the foundation,
> GraphRAG pays for the graph, and Agentic turns ready last.

and a button `Start build` / `Building…` (disabled while running).

### 7.1 Event application (normative reducer)

Each `BuildEvent` is applied to **every pipeline listed in
`pipeline_affected`**, and to no others. Per pipeline, the column state updates:

- `status`: `ready` is **sticky** — once a column is `ready` it stays `ready`
  regardless of later events; otherwise take the event's status.
- `stage`: the event's stage, **except** when the event status is `ready`, in
  which case the previously displayed stage is kept.
- `itemsDone` / `itemsTotal` / `elapsedMs`: overwritten from the event.
- `tokens`: **accumulated** (`+= event.tokens`). Always 0 in practice.
- **Counters**: a stage maps to at most one headline counter, updated with
  `max(current, items_done)` so out-of-order or partial events never regress:

  | Stage | Counter |
  |---|---|
  | `parse_infoboxes` | documents |
  | `chunk_documents` | chunks |
  | `embed_chunks` | chunks |
  | `load_vertices` | vertices |
  | `load_edges` | edges |

  Stages not in the map still drive the progress bar and the log; they just own
  no headline number.
- `log`: the event is appended.

Starting a build resets all three columns, clears errors and cancels any
previous stream. Unmount cancels. Start failure → `Could not start the build`.

### 7.2 Column contents

Per pipeline, in order: label + status badge; current stage title-cased (or
`Not started`); a progress bar at `itemsDone / itemsTotal` (0 when total is 0);
the line `{done} / {total} items`; a metrics row of five tiles — `elapsed`,
`documents`, `chunks`, `vertices`, `edges`; the note
`LLM tokens: {n} (local embedding model)`; and a collapsed disclosure
`{n} stage events` listing every logged event as `stage` + status + note.

A `ready` column is visually distinguished — the moment a pipeline becomes
answerable is the information this screen exists to convey.

Stages in the fixture, in order: `schema_install`, `parse_infoboxes`,
`chunk_documents`, `embed_chunks`, `load_vertices`, `load_edges`,
`vector_index`, `install_q5`, `pipeline_ready` (rag), `install_graph_queries`,
`pipeline_ready` (graphrag), `register_agent_tools`, `pipeline_ready` (agentic).

---

## 8. Screen — Dashboard (`/dashboard`)

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

### 8.1 Headline table

One row per pipeline (with colour swatch): mean **EM**, mean **F1** (2 dp), and
**median** `tokens.total` across the run, rounded and thousands-separated.
Median, not mean, for tokens — deliberate; agentic token counts are long-tailed.

### 8.2 "Is the agent worth it, per question type?"

One row per `QType` (all five always listed, even at n = 0):

| Column | Value |
|---|---|
| Question type | title-cased |
| n | count of scored records of that type |
| `Agentic − RAG EM` | `mean(agentic EM) − mean(RAG EM)`, signed 2 dp, toned by sign |
| `Agentic ÷ RAG tokens` | mean of the **per-question ratio** `agentic.tokens.total / rag.tokens.total`, 2 dp, `×` |
| Verdict | `Worth it` if gap ≥ 0.5; else `Overkill` if gap ≤ 0.05; else `Marginal` |

The ratio is a mean of ratios, not a ratio of means — keep it that way.

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

---

## 9. Screen — Eval table (`/eval`)

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

A small form: label `Run`, a free-text input seeded with the current run id, and
a `Load` button. Submitting sets `?run=<value>` (trimmed; empty clears the
param). Used by both Dashboard and Eval table. Free text, **not** a dropdown —
there is no list-runs endpoint. Known mock ids: `latest`, `hidden`.

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

A redesign may swap in a chart library, provided the **data, axes, tooltips,
legend, per-pipeline colours and theme-responsiveness** survive. Note that CSS
`var()` colours only resolve in CSS, so SVG series colours are applied via
`style`, not the `fill`/`stroke` attributes — keep that or the dark/light switch
will silently stop applying to the charts.

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

Former gaps, now implemented (AUDIT-03) — keep them in any rebuild:

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

---

## 15. Contract to preserve (checklist for the rebuild)

Behaviour, not pixels. Each line maps to something a user or a test depends on.

**Global**
- [ ] Four routes + not-found, with `/` as the search screen
- [ ] `?run=` drives Dashboard and Eval table, and is written by the run picker
- [ ] `mock data` chip appears whenever the mock transport is active
- [ ] Theme toggle, OS default, `ogr-theme` persistence, no flash of wrong theme
- [ ] All API/mock behaviour behind one switch; no view branches on it

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

**Build**
- [ ] One build, fanned out to the pipelines each stage affects
- [ ] `ready` is sticky per column, and a ready column is visually distinct
- [ ] Counters advance monotonically via `max`; tokens accumulate
- [ ] Progress bar, `done / total items`, elapsed, five counters
- [ ] Full stage log per pipeline in a disclosure

**Dashboard**
- [ ] No score is ever recomputed in the browser
- [ ] Headline: mean EM, mean F1, **median** tokens per pipeline
- [ ] Worth-it table with the 0.5 / 0.05 thresholds and mean-of-ratios
- [ ] 5 metrics × 5 qtypes × 3 pipelines matrix, `—` for empty cells
- [ ] Completeness footnoted as an alias of Recall
- [ ] F1-against-tokens scatter with per-point tooltips and a legend
- [ ] Step-count distribution, stop-reason breakdown (desc), strategy-change tiles
- [ ] A run with `scores: null` hides accuracy, keeps the rest, and says why

**Eval table**
- [ ] Every question × three pipelines in one table
- [ ] Disagreement count in the header and a disagree-only filter (FR-20)
- [ ] Normalization used for disagreement only, never for scoring
- [ ] qtype filter, pipeline filter, four sorts, EM-gap sort disabled without gold
- [ ] Gold and score columns hidden with a note when the run has no gold
- [ ] Row drill-down: retrieved doc sets for **all three** pipelines, gold set, verdict line, full trace
- [ ] One row open at a time
- [ ] Empty-filter message

**Cross-cutting**
- [ ] Pipeline order `rag → graphrag → agentic_graphrag` everywhere
- [ ] Pipeline identity colours consistent across columns, tables, charts, ref-type tags
- [ ] Formatting helpers applied uniformly (§11)
- [ ] Loading, empty, error and partial states for every data-backed view

---

## 16. Test hooks that currently exist

The component tests (`frontend/src/SearchView.test.tsx`) drive the UI through
these handles. If the rebuild changes them, update the tests deliberately —
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

React 18 + TypeScript + Vite, `react-router-dom` v6, hand-written CSS with
custom properties, no UI or chart library, no state manager (local `useState`
plus `useSearchParams`), Vitest + Testing Library (jsdom). UI source is ~2,100
lines across 25 files.

None of this is binding on the rebuild. What is binding is everything above it.
