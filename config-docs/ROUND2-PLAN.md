# Round 2 — Implementation plan

Ordered by expected relative-accuracy gain (Agentic vs RAG) first, so the
work can ship at any stopping point. **SAFE** = additive, no schema change,
no re-ingest, no change to the Round-1 answer path. **GATED** = needs the
user's decision recorded in `ROUND2-INTERVIEW-LOG.md`.

**Status (2026-10-24):** steps 1–9 and 11 (offline part) are done on
`round-2`; G2 and G3 are not needed so far; G4 is allowed and not built.
Steps 0, 10, 12 and the live part of 11 need credentials (gate G5: offline
first). The commands are in `ROUND2-RESULTS.md` §3.

| # | Status |
|---|---|
| 0 | not run (no credentials) |
| 1 | done (`pipelines/temporal.py`) |
| 2 | done (`datasets/`) |
| 3 | done (`harness/`) |
| 4 | done (`reasoning/`, `eval/calibration.py`) |
| 5 | done in code (`graph/schema_round2.gsql`, `ingest/load_claims.backfill`); **not yet applied** to the workspace |
| 6 | done in code (`q6_claims`, `q5s_search`, `load_claims`); not yet installed |
| 7 | done through the data: harness records state source and date in their text; no chunker change needed |
| 8 | done (`agents/claims.py`, router, orchestrator, `conflict_resolved`) |
| 9 | done (record/trace fields, result column) |
| 10 | ready (`<name>-dryrun-questions.jsonl`); not run |
| 11 | offline fit and test done (`harness --offline`); live run not done |
| 12 | offline suite passes; live run not done |

Each step is followed by: offline suite (`make check`). From step 4 on,
also the Round-1 live baseline (public-100, three pipelines) and the harness
dev split, once credentials are available.

| # | Step | Files / modules | Kind | Depends on |
|---|---|---|---|---|
| 0 | Re-run the Round-1 live baseline on `round-2` HEAD and record it as the regression reference | `make benchmark` → `out/r2-baseline-public.jsonl` | SAFE (needs credentials) | `.env` |
| 1 | Temporal-intent detector + tests (not yet wired into routing) | `pipelines/temporal.py`, `tests/pipelines/test_temporal.py`, anti-overfitting scan | SAFE | – |
| 2 | Adapter interface + Olympic adapter producing claims from infobox fields (in memory; no graph write) | `datasets/base.py`, `datasets/olympic.py` | SAFE | – |
| 3 | Injection harness: generator, question writer, splits; offline tests of its determinism and of the ground truth | `harness/generate.py`, `harness/templates.py`, `tests/harness/*` | SAFE | 2 |
| 4 | Conflict scorer, supersession and contradiction builder, confidence and calibration (pure functions over ClaimRecords) | `reasoning/resolve.py`, `reasoning/confidence.py`, `eval/calibration.py` (ECE, Brier) | SAFE | 2 |
| 5 | Additive schema: Dataset, Source, Entity, Claim, membership and relation edges; backfill `IN_DATASET` for Round-1 from the registry | `graph/schema_round2.gsql` (SCHEMA_CHANGE JOB, no DROP), `ingest/backfill.py` | **GATED G1** | – |
| 6 | Claim loader (adapter → graph), `q6_claims`, scoped `q5s_search` | `ingest/load_claims.py`, `graph/queries/q6_claims.gsql`, `q5s_search.gsql` | **GATED G1** | 5 |
| 7 | Chunk header with source and publication time (all pipelines see the same provenance), for Round-2 datasets only | `ingest/chunk_embed.py` (adapter-driven) | SAFE for new datasets; Round-1 chunks unchanged | 2 |
| 8 | P3 tools `claims`, `corroborate`, `resolve`; router rule; `conflict_resolved` stop reason | `agents/claims.py`, `router.py`, `orchestrator.py`, `stopping.py` | SAFE in code, active only with claims present | 4, 6 |
| 9 | Record/trace optional fields; frontend confidence badge, conflicts table, time-scope chip | `contracts.py`, `types.ts`, `ResultColumn.tsx`, `TracePanel.tsx` | SAFE (additive) | 8 |
| 10 | Dry run: 10 harness questions × 3 pipelines; cost estimate | `ogr.cli batch --limit 10` | SAFE (needs credentials) | 3, 6–8 |
| 11 | Fit weights, T and thresholds on dev; freeze; run test once; report | `harness/fit.py`, `out/r2-harness-*.jsonl`, `submission/round2-report.md` | SAFE | 10 |
| 12 | Round-1 regression run after steps 8 and 9 | `make benchmark` | SAFE | 8, 9 |
| G2 | LLM-verbalised confidence in the shared answer contract | `contracts.py` (prompt) | **GATED G2**, re-baseline | 0 |
| G3 | Optional `temporal` field in the intent tool call (ambiguous cases) | `intent.py` | **GATED G3**, re-baseline | 1 |
| G4 | LLM claim extraction at ingest (one-time, cached) | `datasets/extract_llm.py` | **GATED G4** | 2 |

## Phase 6 — other enhancements, ranked

Priority order of the brief: (1) relative accuracy gain Agentic vs RAG,
(2) agent reasoning/design quality, (3) token efficiency, (4) engineering and
demo polish.

| Rank | Enhancement | Criterion | Expected impact | Effort | Risk | Recommend |
|---|---|---|---|---|---|---|
| 1 | Generic fact layer + claim tools (steps 5–8) | 1, 2 | Large on a non-Olympic dataset: without it the graph pipelines have nothing to query (X1) | L | Schema change (gated) | **Yes** |
| 2 | Deterministic conflict resolution with cited losers (step 4) | 1, 2 | Large on conflicting subsets; RAG reads several disagreeing chunks with no weighing rule | M | Weights overfit the harness → dev/test split | **Yes** |
| 3 | Temporal scope + supersession (steps 1, 6) | 1 | Large on evolving subsets ("as of", "originally") | M | Over-triggering on Round-1 dates → regression test | **Yes** |
| 4 | Corroboration re-query with a budget | 1, 2 | Medium; only when the margin is low | S | Token cost → capped at 2 calls | **Yes** |
| 5 | Calibrated confidence + ECE/Brier reporting | 2 | Judged design quality; no EM gain by itself | S | Decorative if not validated → test split only | **Yes** |
| 6 | Intent-parse variance: second parse when operation and linked anchors disagree (backlog 2) | 1 | Small (one known public miss) | S | Extra tokens on a few questions | Yes, later |
| 7 | Smaller model for intent parse and evidence check (backlog 13) | 3 | Fewer tokens, lower latency | M | Violates "same LLM in all three" unless applied to all; needs a setup change → **gate** | Ask |
| 8 | Query-embedding cache, off for benchmarks (backlog 12) | 3 | Latency only | S | Hides cost if on in benchmarks | Yes, demo only |
| 9 | Real hybrid retrieval (BM25 + dense) for all pipelines | 1? | Unknown; it helps RAG as much as the agent, so the relative gain may shrink | M | Changes the RAG baseline | No, unless measured |
| 10 | Dashboard: per-subset accuracy, calibration curve, conflicts view; CLI `ogr harness`; MCP tool surface over `/query` | 4 | Demo clarity | M | None to accuracy | Yes, after 1–5 |
| 11 | Prompt-injection red-team set (backlog 16) | 4 | Robustness evidence | S | – | Yes, small |
