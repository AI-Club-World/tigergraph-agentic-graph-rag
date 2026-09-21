---
path: specs/004-ui-batch-eval/implementation-plan-UI.md
implements_tasks: CORE / LLM / EVAL / API / WEB / HID
level: implementation-plan
derived_from: TECHNICAL-SPEC.md, APPLICATION-SPEC.md, ARCHITECTURE-SPEC.md
cache: volatile
tier: LOCALISED
gate: G0 -> G6
status: approved
plan_id: PLAN-004
task_tracker: ./task.md
sub_plans: []
---

# UI (interactive surface + batch/eval consumers) — Implementation Plan

**Module name**: taken verbatim from MODULE-BREAKDOWN.md § "Module: UI (interactive surface + batch/eval consumers)"
**Source spec**: TECHNICAL-SPEC §4, §5, §6, §9, §10 · APPLICATION-SPEC FR-1…FR-15 · ARCHITECTURE-SPEC §2, §8, §9
**Repository**: https://github.com/AI-Club-World/tigergraph-agentic-graph-rag
**Workspace**: `backend/src/ogr/{api,common,eval}/`, `frontend/src/`
**Task tracker**: [task.md](./task.md)
**Stack (fixed)**: FastAPI + `sse-starlette` · React (Vite) · Python 3.11
**Effort (T1 scope)**: 19 pt of the 60 pt Round-1 target

> **Read this plan first.** Group 0 freezes the record contract that PLAN-001,
> PLAN-002 and PLAN-003 all write against. Nothing else in any module starts
> until Group 0 lands.
>
> **Revised from T0**: the interactive UI is back in scope by decision, and a
> **second** three-column surface has been added for the build/ingest phase,
> which appears in no existing spec. Scope moved 34 → 45 pt. See §"Scope
> reality" at the foot of this plan before committing to it.

---

## Research Summary

Verified against the supplied data and the fixed stack, not inferred.

- **Current state**: greenfield. No repository exists. Verified by inspecting
  `/mnt/user-data/uploads` — only spec markdown and the three dataset files.
- **Gaps identified**: **11 distinct** across 6 groups.

**Data findings (unchanged, all verified by parsing the files):**

- **The batch contract matches neither data file.** TECHNICAL-SPEC §4.3 expects
  `question_id` / `text`; both `eval_public.jsonl` (100) and
  `eval_hidden.jsonl` (50) use `qid` / `question` / `qtype`. The F-14
  normalization adapter is unnecessary and would corrupt the public set.
- **`ground_truth` is mistyped** as `string | null`; every public record carries
  `answer` as a list. §9 already specifies max-over-variants.
- `answer_verified` (all `true`), `answer_named_in_question` (all `false`) and
  `guess_baseline` (all `0.0`) are constant and carry no signal.
- **Completeness duplicates Recall**; **Precision@k is undefined for P2 and P3**,
  which retrieve by traversal and have no `k`.
- All 518 distinct `gold_doc_ids` resolve to corpus `doc_id`s with zero misses;
  `doc_id == wikidata_qid` throughout. No ID mapping layer.
- **The hidden run is guidebook-mandatory** — raw outputs for all 50, including
  tokens and agentic trace. Batch runner and store cannot be cut.
- **Two guidebook-required trace fields are missing** from §6.2/§6.3: chunk
  count and citation count.

**Findings forced by the new UI requirement and the fixed stack:**

- **Streaming as specified cannot work in a browser.** TECHNICAL-SPEC §4.1
  streams the response to `POST /query`; §5 specifies SSE. The browser
  `EventSource` API is **GET-only**. A POST cannot be consumed by `EventSource`.
  This is now binding on two surfaces, not one, since the build view also
  streams. See DP-5.
- **"Build in parallel for RAG, GraphRAG and Agentic" does not match the
  architecture as specified.** There are not three builds. MODULE-BREAKDOWN's
  own dependency graph states GraphRAG owns schema, ingestion, embeddings and
  the query library, and that RAG and Agentic *consume* them. Chunk+embed feeds
  all three; schema+parse+load feeds two; nothing is RAG-exclusive. Three
  columns racing each other would be theatre. See DP-6 for three honest ways to
  render this.
- **Build-phase token counts are structurally zero.** Ingestion is deterministic
  parsing plus a *local* embedding model (AD-6) — no LLM, no provider call. The
  requested build-phase token metric has no true non-zero value unless LLM
  entity extraction is added, which contradicts the hand-designed schema and
  AD-4. The build columns must report time, documents, chunks and vertices.
- **The query-phase 3-column view is well-supported**: per-column independent
  rendering is already FR-3/FR-4, and LangGraph's `astream_events` (PLAN-003)
  produces the trace stream the panel consumes.
- Scoring remains **fully testable before TigerGraph exists**. It consumes
  records, not the graph. This is still the largest schedule lever available.

> Not read, therefore not asserted: real SSE behaviour through whatever proxy
> the demo runs behind. `[NEEDS CLARIFICATION]` — verified at G3, not assumed.

---

## Design Decisions Required Before Implementation

> [!IMPORTANT]
> Implementation does not begin on a DP until it is selected.
> An agent MAY recommend; a human decides.

### DP-1 — Record schema freeze (blocks all four modules)

**Gap**: §6 does not match the supplied data, omits two guidebook-required
counts, and contradicts MODULE-BREAKDOWN RAG-04 on citation granularity.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Data field names verbatim (`qid`, `question`, `qtype`); `ground_truth: list[str]`; citations carry both `source_id` (parent `doc_id`, scored) and `chunk_id` (displayed); add `chunks_returned` + `citations_count` to `PipelineRecord` and `TraceStep` | Low, day 0 | No | Matches data, satisfies the guidebook trace list, fixes the RAG-04 contradiction |
| B | Keep §6, add an adapter | Medium | Yes, later | Adapter exists only to translate a spec error into itself |
| C | Freeze a minimal subset, extend later | Low now, high later | Yes | Guarantees a breaking change mid-build |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-2 — Metric set and Completeness

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Precision / Recall / F1 over the returned document set for all 3 pipelines; `k=10` for P1 only, stated; Completeness presented as an explicit alias of Recall, footnoted | Low | No | Honest and comparable; keeps the guidebook's named column |
| B | Keep Recall@k and Completeness as separate columns | Low | No | They are the same number |
| C | Drop Completeness | Low | No | Loses a named dashboard column |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-3 — Batch output storage

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Append-only JSONL per run + sibling `run_config` header | Low | No | Diffable (NFR-4 names this), resumable, zero migration cost, and it is what the dashboard reads |
| B | SQLite | Medium | No | Earns its place only if the dashboard needs ad-hoc queries |
| C | TigerGraph vertices | High | No | Couples the eval record to the system under test |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-4 — Hidden-set handling protocol

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | `acceptance/holdout/eval_hidden.jsonl`; only `batch_runner --holdout` opens it; no human and no code assistant reads its contents; run once after G5; CI grep enforces | Zero | No | Makes the template's holdout rule literally true and survives N assistants with filesystem access |
| B | Convention stated in README | Zero | No | Unenforceable |
| C | No restriction | Zero | No | Invites the failure the risk register names first |

**Recommendation**: Option A.
**Escalate if**: hackathon rules prohibit relocating the file.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-5 — Streaming transport (blocks both three-column surfaces)

**Gap**: `POST /query` cannot be consumed by browser `EventSource`. Both the
query trace panel and the build progress view need a stream.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | `POST /query` returns `202 {query_id}` immediately; `GET /query/{id}/stream` and `GET /build/{id}/stream` carry SSE via `sse-starlette`; React uses native `EventSource` | S | Amends §4.1 | Smallest change, matches the existing `/result` path shape, gets auto-reconnect free, one transport for both surfaces |
| B | Keep POST, consume with `fetch` + `ReadableStream` in React | M | No | Works, but hand-rolls SSE parsing and loses reconnect — on a live demo, reconnect is the feature you want |
| C | WebSocket | M | Replaces §5 | Only justified if cancel/interrupt becomes a requirement; §5 already decided against it |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-6 — Semantics of the three-column **build** view

**Gap**: new requirement with no spec basis, and the architecture has one shared
foundation rather than three independent builds. Whatever is chosen, a judge
may ask "what is the RAG column actually building?"

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | One shared build; three columns show **per-pipeline readiness** over the shared stages, each stage fanned out to the pipelines it unblocks via `BuildEvent.pipeline_affected` (PLAN-001). RAG turns ready after chunk+embed and Q5; GraphRAG after schema+parse+load+library; Agentic last. Columns show elapsed time, docs/chunks/vertices, and a ready badge | S | No | Honest, matches the real dependency graph, visually demonstrates that GraphRAG carries setup cost RAG does not — which is itself part of the cost argument |
| B | Three genuinely separate build artifacts (separate vector index for RAG, separate graph build, separate agentic tool registry) | L | Yes — restructures ingestion | Gives three truly independent progress bars and three real timings, at the cost of duplicated embedding work and a rewrite of PLAN-001 Group 2 on day 2 |
| C | Single progress bar for build; three columns only on the search surface | S | No | Cheapest and defensible, but does not deliver the requested build view |

**Recommendation**: Option A. It delivers the three-column build experience
asked for, needs no ingestion restructure, and the staggered readiness is a
truthful picture rather than a staged race. Option B is the only one that
produces three independent build *timings*, and it is not affordable in the
remaining window.
**Escalate if**: the requirement is specifically three independently-timed
builds for the demo narrative — that is a product decision, not an agent's.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-7 — Build-phase metrics, given that build tokens are zero

**Gap**: the requirement asks for "tokens, time, etc" on the build columns;
ingestion makes no LLM calls (AD-6), so tokens are structurally 0.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Show wall-time, documents processed, chunks embedded, vertices/edges written, and an explicit `LLM tokens: 0 (local embedding model)` line | S | No | The zero is a selling point — it is AD-6's whole argument, and labelling it beats hiding it |
| B | Omit the token row on build columns | S | No | Invites the question "why is it missing" |
| C | Add LLM-based entity extraction so build tokens are non-zero | L | Yes | Contradicts the hand-designed schema and AD-4; buys a number at the cost of the thesis |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-8 — Authenticating the SSE streams

**Gap**: backend routes must be API-key protected, but browser `EventSource`
cannot send custom headers, so `X-API-Key` is unavailable on exactly the two
endpoints the UI depends on most.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | `POST /query` and `POST /build` return `{id, stream_token}`; the `GET …/stream` endpoints accept `?token=`, single-use, scoped to that id, expiring in minutes | S | No | The long-lived key never enters a URL, browser history or access log; the token is worthless once used |
| B | Pass the API key itself as `?api_key=` | S | No | Puts the credential in access logs, referrers and browser history — the classic secret-in-URL defect |
| C | Cookie-based session | M | No | Works with `EventSource`, but introduces session state and CSRF surface for a single-user demo tool |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

---

## Open Questions (non-blocking)

- React state management: local state is sufficient for two screens; no store.
- Whether the dashboard is a React route reading batch JSON or a separate
  static HTML file. Reusing the column components argues for the route.
- `run_id` format (timestamp vs UUID).
- Dashboard styling. Numbers are judged, not CSS.

---

## Proposed Changes

### Group 0 — Contract freeze (1 pt) · **day 0, before anything else**

#### ADD `backend/src/ogr/common/models.py`
- Pydantic: `Question`, `Citation`, `TraceStep`, `PipelineRecord`,
  `QueryLevelRecord`, `BatchRecord`, `RunConfig`, `BuildEvent`, per DP-1.
- Loading both eval files validates with zero coercion warnings.
- **Requirement**: `FR-14`, `NFR-5` · **Gate**: `G0`
- **Rollback**: single file; no consumers exist yet.

#### ADD `backend/src/ogr/common/config.py`, `.env.example`, `config/run_config.yaml`
- Env-var loading for Savanna and the LLM key. No secret enters a persisted
  record or an SSE frame.
- **Requirement**: `NFR-4` · **Gate**: `G0`
- **Rollback**: revert.

### Group 1 — Scorer (3 pt) · **TigerGraph-independent, starts day 0 in parallel**

#### ADD `backend/src/ogr/common/names.py`
- SQuAD-style normalizer. Multi-person splitter on lowercase→uppercase
  boundaries **with a guard** for `Mc|Mac|O'|Di|De|Van|Le|La`. Verified
  necessary: the naive rule mis-splits `Rosannagh MacLennan` (pub-067). Genuine
  concatenations are pub-015 and pub-099 only.
- **Requirement**: `FR-14` · **Gate**: `G3`
- **Rollback**: pure functions; revert independently.

#### ADD `backend/src/ogr/eval/scorer.py`
- EM, token F1, precision/recall/F1 over the returned doc set, Completeness as
  the recall alias (DP-2), per-qtype breakdown. No LLM in this path.
- **Requirement**: `FR-14`, `NFR-6` · **Gate**: `G3`
- **Rollback**: revert; batch degrades to raw-record capture.

### Group 2 — Dispatcher, Aggregator, API (4 pt)

#### ADD `backend/src/ogr/eval/dispatcher.py`
- `asyncio.gather` over three pipeline callables, each in its own `try/except`;
  failure yields a `PipelineRecord` with `status="error"`, never a raised
  exception.
- **Requirement**: `FR-2`, `NFR-1`, `NFR-2` · **Gate**: `G2`
- **Rollback**: sequential invocation; records unchanged.

#### ADD `backend/src/ogr/eval/aggregator.py`
- Merges 3 records into `QueryLevelRecord`; verdict with
  `token_multiplier_vs_rag`, `token_multiplier_vs_graphrag`,
  `accuracy_delta_vs_rag`, `accuracy_delta_vs_graphrag`, `"n/a"` where no
  ground truth (FR-9). One implementation, used by API and batch alike (AD-1).
- **Requirement**: `FR-8`, `FR-9`, `NFR-5` · **Gate**: `G2`
- **Rollback**: revert; records lose the verdict block only.

#### ADD `backend/src/ogr/api/main.py`
- FastAPI: `POST /query` → `202 {query_id}` · `GET /query/{id}/stream` (SSE) ·
  `GET /query/{id}/result` · `POST /build` → `202 {build_id}` ·
  `GET /build/{id}/stream` (SSE) · `GET /runs/{run_id}/records`. Per DP-5.
- **API-key auth on every route** except `/health`: `X-API-Key` header checked
  against `OGR_API_KEY` from configuration, as a FastAPI dependency applied at
  the router level so a new endpoint is protected by default rather than by
  remembering.
- **SSE cannot carry the header.** Browser `EventSource` does not support custom
  headers, so the two stream endpoints are authenticated by a **short-lived,
  single-use stream token** returned alongside the id from `POST /query` and
  `POST /build`, passed as `?token=`. The long-lived API key never appears in a
  URL, a browser history entry or an access log (DP-8).
- Bound to `127.0.0.1` by default; `--host 0.0.0.0` must be explicit. Defence in
  depth: a key shipped to a browser is not a secret, so the binding still matters.
- **Requirement**: `FR-1`, `FR-13`, TECHNICAL-SPEC §4, §5 · **Gate**: `G3`
- **Rollback**: CLI remains a complete path to every capability.

### Group 3 — React: three-column search surface (4 pt)

#### ADD `frontend/` (Vite + React)
- `QueryInput` — one field, one submit (FR-1).
- `ResultColumn` ×3 — **independent** running / done / error states; a column
  renders as soon as its own pipeline finishes and never waits on the others
  (FR-3, FR-4, NFR-2). Each shows answer, citations, `tokens.total`
  (input/output split on hover), `latency_ms`, and for P3 the `stop_reason`.
- `VerdictStrip` — renders once all three complete; token multipliers and
  accuracy delta or `"N/A"` (FR-8, FR-9).
- **Requirement**: `FR-1`, `FR-3`, `FR-4`, `FR-8`, `FR-9` · **Gate**: `G5`
- **Rollback**: CLI comparison output; demo recorded against it.

#### ADD `frontend/src/TracePanel.tsx`
- `EventSource` on `GET /query/{id}/stream`; appends each `TraceStep` as it
  arrives; marks `strategy_change: true` steps visibly (FR-5, FR-6).
- **Requirement**: `FR-5`, `FR-6`, `FR-7`, `AD-2` · **Gate**: `G5`
- **Rollback**: render the trace from the completed record; loses live
  accumulation, which is the point of AD-2 — degrade only under time pressure.

### Group 4 — React: three-column build surface (2 pt) · **new requirement**

#### ADD `frontend/src/BuildView.tsx`
- Three columns (RAG / GraphRAG / Agentic) driven by one `EventSource` on
  `GET /build/{id}/stream`, fanned out by `BuildEvent.pipeline_affected` per
  DP-6 Option A.
- Per column: current stage, progress (`items_done / items_total`), elapsed
  time, documents and chunks processed, vertices/edges written, ready badge,
  and `LLM tokens: 0 (local embedding model)` per DP-7.
- **Requirement**: new · **Gate**: `G5`
- **Rollback**: single progress view (DP-6 Option C); search surface unaffected.

### Group 5 — Batch runner, store, dashboard (4 pt)

#### ADD `backend/src/ogr/eval/batch_runner.py`
- **Latency is only comparable from a controlled run.** The dispatcher already
  runs 3 pipelines concurrently; a batch pool of 6 questions means up to 18
  in-flight provider calls, and provider-side queuing then inflates
  `latency_ms` unevenly across pipelines. Two run modes: `--throughput`
  (pool 6, used for accuracy and token metrics, which are unaffected) and
  `--timing` (pool 1, used for the latency figures that appear in the
  dashboard). The run header records which mode produced the record; the
  dashboard labels latency accordingly. Tokens are pool-invariant, latency is not.
- Pool size, requests-per-minute and backoff come from `run_config`, defaulting
  to **2 concurrent on cloud free tiers and 6 locally** (PLAT-08). Free-tier
  rate limits are the most likely cause of a partial run, and a partial run
  discovered at hour 60 is unrecoverable.
- Bounded pool, exponential backoff on 429,
  `max_total_tokens` abort (run-level cost ceiling — AGENT stopping criteria
  bound a query, not a run).
- Resume by skipping `qid`s already in the output file. Pick this **or**
  LangGraph checkpointing, not both.
- `--holdout` is the only path permitted to open `acceptance/holdout/`.
- **Requirement**: `FR-13`, `FR-15`, `NFR-4` · **Gate**: `G5`, `G6`
- **Rollback**: serial loop; slower, same output.

#### ADD `backend/src/ogr/eval/store.py`
- Append-only JSONL + `run_config` header. Write-time assertion that no value
  matches an API-key shape.
- **Requirement**: `NFR-4` · **Gate**: `G5`
- **Rollback**: stdout.

#### ADD `frontend/src/Dashboard.tsx` — **aggregate benchmark view**
- Per-qtype matrix (5 metrics × 5 qtypes × 3 pipelines), accuracy-vs-tokens
  scatter, agentic step-count distribution, strategy-change frequency,
  stop-reason breakdown.
- Headline panel answering the core question directly: overall EM/F1 per
  pipeline, median tokens per pipeline, and the **agentic-vs-RAG accuracy gap
  per qtype beside the token multiplier per qtype** — the two numbers whose
  ratio decides "worth it" or "overkill" for each question type.
- **Requirement**: TECHNICAL-SPEC §10 · **Gate**: `G5`
- **Rollback**: CLI table + screenshots (ARCHITECTURE-SPEC §13 fallback).

#### ADD `frontend/src/EvalTable.tsx` — **all 100 eval questions × 3 pipelines**
- One row per evaluation question, three column groups (RAG / GraphRAG /
  Agentic), each showing answer, EM, F1, precision/recall, tokens, latency,
  citation count, and for P3 the step count and `stop_reason`.
- Gold answer and `gold_doc_ids` shown alongside, so a judge can check a verdict
  without leaving the row.
- Sort and filter by qtype, by pipeline, and by "pipelines disagree" — the
  disagreement filter is where the whole research question lives.
- Row click opens the drill-down: full `TraceStep[]` for the agentic run and the
  retrieved document sets for all three.
- Same component renders the **50 hidden-question run** with the gold columns
  absent, since no answers are supplied for those.
- **Requirement**: `FR-15`, guidebook "metrics dashboard comparing the three
  pipelines" · **Gate**: `G5`
- **Rollback**: CSV export of the same table, opened in a spreadsheet for the
  demo video.

#### ADD `backend/src/ogr/cli.py`
- `build`, `ask`, `batch`, `score`, `dashboard`. The CLI is the fallback demo
  surface and the thing `make reproduce` calls — it must stay complete even
  once the UI exists.
- **Requirement**: `FR-13` · **Gate**: `G5`
- **Rollback**: none.

### Group 6 — Reproducibility and submission (2 pt)

#### ADD `Makefile`, `Dockerfile`, `ATTRIBUTION.md`
- `make reproduce`: clean clone → deps → ingest → embed → install queries →
  100-question run → dashboard. No manual steps. Budget 20–40 min and say so.
- `ATTRIBUTION.md` covers CC BY-SA 4.0 for the corpus **and** any committed
  derived data (parsed infoboxes, chunk files) — share-alike reaches those too.
- **Requirement**: `NFR-4`, TECHNICAL-SPEC §12 · **Gate**: `G6`
- **Rollback**: documented manual steps, which forfeits rubric credit.

---

## Verification Plan

### Automated

```
pytest -q backend/tests/common tests/eval tests/api
cd frontend && npm run build && npm test
python -m ogr.cli score --run out/run-latest.jsonl --assert-against tests/fixtures/hand_scored.json
```

| Group | New tests | Command | Verdict |
|---|---|---|---|
| 0 | `test_models_load_both_eval_files` | `pytest -q backend/tests/common/test_models.py` | `unmeasured` |
| 1 | `test_em_f1_matches_hand_computed`, `test_maclennan_not_split`, `test_pub015_pub099_split` | `pytest -q backend/tests/eval/test_scorer.py` | `unmeasured` |
| 2 | `test_one_pipeline_error_does_not_block_others`, `test_verdict_na_without_ground_truth`, `test_post_query_returns_202_immediately` | `pytest -q backend/tests/eval tests/api` | `unmeasured` |
| 3 | `test_columns_render_independently` (one column done while two running), `test_trace_appends_on_sse_event` | `cd frontend && npm test` | `unmeasured` |
| 4 | `test_build_event_fans_out_to_affected_pipelines` | `pytest -q backend/tests/api/test_build_stream.py` | `unmeasured` |
| 5 | `test_resume_skips_written_qids`, `test_no_secret_in_persisted_record`, `test_dashboard_renders_all_qtypes` | `pytest -q backend/tests/eval` | `unmeasured` |
| 6 | `make reproduce` on a clean clone in a fresh container | `make reproduce` | `unmeasured` |

- **Holdout**: `acceptance/holdout/eval_hidden.jsonl` is not readable by any
  implementing agent; opened only by `batch_runner --holdout`, once, after G5.
  CI greps that no other source file references the path.
- **Unmeasured is a real outcome.** A test not run is `unmeasured`, never `pass`.

### Manual

- Hand-compute EM and token F1 for pub-001, pub-014 and pub-067; confirm
  `scorer.py` reproduces all three exactly. This is the **G3** trigger.
- Submit one query in the browser and watch the three columns populate at
  visibly different times. If they appear together, the dispatcher is
  serialising and NFR-1 is unmet regardless of what the code looks like.
- Run a full build and confirm the three columns turn ready in dependency
  order — RAG before Agentic — rather than simultaneously.

---

## Execution Order

1. Group 0 → **verify**: both eval files parse into `Question`
2. Group 1 → **verify**: hand-scored fixtures match (**G3** — reachable on day 0,
   with no graph, no LLM, no provisioning)
3. Group 2 → **verify**: fault isolation against a deliberately throwing stub;
   `POST /query` returns before any pipeline finishes
4. Group 3 → **verify**: columns render independently against stubbed SSE
   (build the React surface against stubs, then re-test at G2 against real
   pipelines — DELIVERY-STREAMS already names "mocked data never re-tested" as
   an integration risk, so the re-test is a step, not an intention)
5. Group 4 → **verify**: fan-out test
6. Group 5 → **verify**: 100-question dry run on stubs, resume tested by killing
   mid-run; then the real run at **G5**
7. Group 6 → **verify**: `make reproduce` in a fresh container (**G6**)

---

## Sub-plan externalization

| Sub-plan | Scope | File | Status |
|---|---|---|---|
| PLAN-004-a | Groups 3–4 React surfaces, if handed to a dedicated assistant | ./plans/group-3-web.md | not created |

---

## Scope reality

The per-question eval table adds 1 pt (46 pt total). Adding both three-column surfaces moves the Round-1 target from 34 pt to
**45 pt ≈ 22 person-days**, against roughly 3 days. This is worth stating
plainly rather than discovering on day 3.

Cut ladder, in the order I would apply it:

1. **Build view → single progress bar** (DP-6 Option C). −2 pt. The search
   surface is the demo; the build view is setup.
2. **Live trace panel → trace rendered from the completed record.** −1 pt.
   Costs AD-2's "judges see cost accumulate live", keeps every number.
3. **Dashboard → static HTML from batch JSONL**, not a React route. −1 pt.
4. **P3 restricted to LOOKUP / COUNT / ARGMAX**, with multi_hop and temporal
   declared as known limitations in the README. −3 pt.

What never gets cut: the scorer, the batch runner, the hidden-set run, and
`make reproduce`. Those carry 60% of the rubric between them, and the hidden
run is mandatory.

---

## Stop conditions

- DP-1 unselected once any other module starts serializing records
- DP-5 or DP-6 reached unselected — both block React work
- A change would require editing `backend/tests/fixtures/hand_scored.json` to make the
  scorer pass
- Anything reads `acceptance/holdout/` outside the batch runner
- An LLM call appears in `scorer.py` (violates NFR-6 and AD-4)
- The three columns render in lockstep — stop and fix the dispatcher before
  building anything further on top of it
- Group 1 not green by end of day 1 — escalate; the scoring layer is what makes
  every other module measurable
- Wall-clock: if the search surface is not rendering real pipeline output by
  midday of day 3, apply the cut ladder above rather than compressing
