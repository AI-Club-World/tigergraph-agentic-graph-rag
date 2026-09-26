# CONTINUE.md — start here

Handoff for picking this project up fresh, on a new machine or a new session.
Written 2026-09-22 against `application-integration` @ `6291601`.

> **Update, same day, later commit.** Everything this file originally said
> was missing — GSQL queries, ingestion beyond the infobox parser, the HTTP
> API, the batch runner — has since been **written and unit-tested against
> mocks**: `graph/schema.gsql`, `graph/queries/q{1..5}_*.gsql`,
> `ingest/chunk_embed.py`, `ingest/load.py`, `graph/vector_status.py`,
> `ingest/progress.py`, `eval/batch_runner.py` + `eval/store.py`, and
> `api/main.py` (FastAPI + SSE + API-key auth, routes matching the frontend
> exactly). 283 backend tests pass. **What is still true, and still blocks a
> real run**: none of the GSQL has been installed against a live TigerGraph
> workspace (`TG_HOST` is still empty), so §3's blocker chain below is
> accurate for *live verification*, not for *code existing*. The GRAPH-04
> chunk+embed step has been run for real against the actual 2,951-document
> corpus (`out/chunks.jsonl`, 16,669 chunks) — that part needs no TigerGraph
> and is genuinely done, not just written.

Read this file top to bottom before changing anything. It is written to be
self-contained: you should not need the conversation that produced it.

---

## 1. The one-paragraph state of things

Three RAG pipelines are **implemented and unit-tested** (283 backend tests,
all green), the React UI is **built and deployable**, the LLM and TigerGraph
client boundaries both **read real credentials and make real calls**, and
the schema, query library, ingestion, batch runner and HTTP API are now
**written and unit-tested against mocks** (see the update note above). But
the system **has still never run end to end against a live graph**, because
no GSQL has been installed against a real TigerGraph workspace yet —
`TG_HOST` is empty and the configured LLM key has no credits.

Nothing here is broken. It is unverified live in a specific, well-understood place.

## 2. What runs today, verified

| Thing | Command | Result |
|---|---|---|
| Backend tests | `cd backend && python -m pytest -q` | **185 pass** |
| Backend lint | `cd backend && python -m ruff check src tests` | clean |
| Frontend build | `cd frontend && npm run build` | succeeds |
| Frontend lint | `cd frontend && npm run lint` | clean |
| Frontend tests | `cd frontend && npm test` | 2 pass |
| Frontend dev server | `cd frontend && npm run dev` | http://localhost:5173 |

Every one of those runs against **mocks and fixtures**. None of them touches a
live TigerGraph or a live LLM. A green suite here does not mean the system
works — it means the logic is internally consistent.

First-time setup: `cd backend && pip install -e ".[dev]"` and
`cd frontend && npm install`.

## 3. The blocker chain — read this before planning anything

The gaps are not independent. They form a chain, and the first link is fatal:

```
  no corpus.jsonl          ->  nothing to ingest
  no ingest code           ->  graph stays empty
  no .gsql files           ->  client.runInstalledQuery() finds no query
  no api/ module           ->  frontend cannot reach the backend
```

`backend/src/ogr/graph/client.py` already calls `runInstalledQuery("q1_lookup")`,
`("q5_hybrid_search")` and friends. **Those queries do not exist anywhere in
this repo.** Point the client at a live TigerGraph right now and every call
returns empty — not an error, just nothing. That silence is the single most
misleading thing about the current state, so it is worth knowing first.

## 4. Three things you must supply — they cannot be written

| # | Needed | Why | Notes |
|---|---|---|---|
| 1 | `corpus.jsonl` (2,951 docs) and `eval_public.jsonl` (100 questions) | Nothing to ingest or score without them | Referenced all through the specs; **not in the repo**. Expected at `data/`. Also `eval_hidden.jsonl` (50), which belongs at `acceptance/holdout/` and must be opened by the batch runner only |
| 2 | A TigerGraph workspace | Vectors *and* graph both live there — this is a hackathon eligibility condition, so no FAISS/Chroma/pgvector substitute | Savanna, or local Community Edition 4.2+. Fill `TG_HOST`, `TG_USERNAME`, `TG_PASSWORD`, `TG_SECRET` in `.env` |
| 3 | An LLM endpoint | Intent parsing, generation, groundedness | Free options: Ollama locally (`LLM_BASE_URL=http://localhost:11434/v1`, no key), or any free-tier OpenAI-compatible cloud key. Set `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` |

Copy `env.example` to `.env` at the repo root and fill it in. `.env` is
git-ignored; **never commit real values**, and never put a secret in a
`VITE_`-prefixed variable — those are compiled into the browser bundle.

## 5. What to build next, in order

Estimates are BUILD-PLAN's own (S=1, M=2, L=3 points; 1pt ≈ half a day).

| Order | Task | Pt | Produces |
|---|---|---|---|
| 1 | `GRAPH-01` schema + idempotent install | 2 | Vertex/edge types per TECHNICAL-SPEC §2, endpoints pinned |
| 2 | `GRAPH-02` infobox parser + sport derivation | 2 | Parsed `OlympicEvent` rows + a coverage report |
| 3 | `GRAPH-04` chunk + embed **all 2,951 docs** | 2 | Chunks with 1024-dim (bge-m3) vectors in TigerGraph |
| 4 | `GRAPH-05` load vertices/edges | 1 | A populated graph, `PREV_EDITION`/`NEXT_EDITION` resolved |
| 5 | `GRAPH-06` vector-readiness gate | 1 | Polls `/restpp/vector/status` for `Ready_for_query` |
| 6 | **`GRAPH-07` write and install Q1–Q5** | 3 | **Makes the existing client actually work** |
| 7 | **`API-01` FastAPI + SSE + API key** | 2 | **Makes the existing frontend actually work** |
| 8 | `EVAL-04` batch runner + JSONL store | 3 | The 100-question scored run |

`GRAPH-03` (date normalizer) is **already done** — `backend/src/ogr/common/dates.py`.
Do not write a second one; P3's entity linker imports that exact module.

### Smallest milestone that proves the system is real

Steps 1–5, then **Q5 only**, then `API-01`. That gets **P1 running end to end**
against a real graph and a real LLM. P2 and P3 need Q1–Q4 on top. Aim for that
before anything else — it converts "unit tests pass" into "it works", which is
a different kind of claim.

## 6. Repo orientation

```
backend/src/ogr/
  common/      config, contracts (the record schemas), llm (the ONE model
               boundary), embeddings, dates, names
  graph/       client.py — TigerGraph access, calls Q1-Q5 by name
  pipelines/   p1_rag.py · p2_graphrag.py · p3_agentic/ (orchestrator,
               intent, router, evidence, stopping, strategy, trace, agents/)
  eval/        scorer, dispatcher, aggregator
  ingest/      <- DOES NOT EXIST YET
  api/         <- DOES NOT EXIST YET
backend/tests/ mirrors the above; 185 tests
frontend/src/  React + Vite UI, runs on src/fixtures/ by default
scripts/       spike_vector.py — an untested vector spike from feature/graph-rag
config-docs/   all specs, plans, audit, integration and deploy notes
```

**Read these before writing code**, in this order:
`config-docs/BUILD-PLAN.md` (task table and gates) →
`config-docs/TECHNICAL-SPEC.md` (§2 schema, §3 the five queries, §6 record
contracts) → `config-docs/AUDIT.md` (what is implemented, with evidence) →
the `implementation-plan-*.md` for whatever you are building.

Branches: `application-integration` is the trunk and holds everything. The
four `feature/*` branches are merged into it and left at their original tips.
`feature/agentic-rag` is **empty** — the agentic work is on
`feature/implementation-rag`. See `config-docs/INTEGRATION.md`.

## 7. Decisions already locked — do not re-litigate

These were argued out and committed. Changing one means changing the specs
and the tests that enforce it.

| Decision | Where |
|---|---|
| P1 is **deliberately unfiltered** — no re-ranking, no type filter, no threshold. Its ceiling must stay visible | AD-9; `tests/pipelines/test_p1_unfiltered.py` guards it |
| P2 reuses P3's intent parser and runs **exactly one query**, no loop. That one variable *is* the experiment | PLAT-07; `tests/pipelines/test_p2.py` |
| `qtype` is an eval-set label and is **never read in the answer path** | NFR-7; `tests/pipelines/p3/test_anti_overfitting.py` |
| No LLM in the **scoring** path. EM/F1 are deterministic | NFR-6, AD-4 |
| Σ `TraceStep.tokens` **must equal** the record total | DP-5; `test_token_reconciliation.py` |
| Vectors live **in TigerGraph**. No FAISS, Chroma or pgvector | BUILD-PLAN §1 — eligibility condition |
| Chunk 300 / overlap 50 / `k`=10, fixed before the first run, never tuned against results | PLAN-002 DP-1 |

Two CI guards exist because assistants write this code: a **holdout grep**
(only `eval/batch_runner.py` may reference `acceptance/holdout/`) and a
**no-test-modified** check (changing tests and source together needs a
`TEST-CHANGE:` line in the commit message with a reason). Both are in
`.github/workflows/ci.yml`.

## 8. Gotchas that will cost you an hour each

- **`client.py` fails silently.** No TigerGraph connection, or a missing
  query, returns `[]` and logs a warning. It does not raise. If a pipeline
  returns an empty answer, check the graph before debugging the pipeline.
- **`npm ci` can fail on Windows** with "operation was rejected by your
  operating system" if a dev server or antivirus holds `node_modules`. Stop
  the dev server first. `npm install` is more forgiving.
- **The frontend needs an SPA rewrite** or `/dashboard`, `/eval` and `/build`
  404 on refresh. Handled two ways already: `netlify.toml` for Git-linked
  builds, `frontend/public/_redirects` for folder deploys. Do not delete
  either.
- **`.pyc` files were committed once** and later untracked. If you see them
  reappear, `.gitignore` covers them — do not re-add.
- **Deploying:** Netlify's free tier will **not** Git-deploy this repo — it is
  private and org-owned, which is a Pro feature. Deploy the built folder
  instead. See `config-docs/DEPLOY.md`.

## 9. Working from a phone

Realistic about what the device can do:

**Workable:** reading the specs and `AUDIT.md`, planning, writing the schema
and GSQL queries (they are text and need no local runtime), reviewing diffs,
and driving a coding agent against the repo.

**Not workable on-device:** running TigerGraph, `pip install -e ".[dev]"`,
`npm install`, or the test suites. Anything in §5 that needs verification will
need a real machine or a cloud dev environment.

**Suggested split:** draft the GSQL for Q1–Q5 and the schema on mobile — they
are pure text against TECHNICAL-SPEC §2 and §3 — then verify and install from
a laptop with a workspace connected. Do not mark a task done from a phone; the
project's whole discipline is that "unmeasured" is a real outcome and a test
not run is never a pass.

## 10. Honest summary to carry forward

Say this, not more: *three pipelines and a UI are implemented and unit-tested;
the system has not been run against a real graph or a real LLM; the ingestion
layer, the five GSQL queries and the HTTP API are the remaining work.*

`config-docs/AUDIT.md` has the item-by-item evidence if anyone wants detail.
