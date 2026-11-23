# Round 2 - Plan

Current plan for the real brief, through the submission deadline
(**29 Nov 2026, 23:59 IST**). Written 2026-11-23. Contract:
[SOLUTION-DESIGN.md](SOLUTION-DESIGN.md); requirements:
[APPLICATION-SPEC.md](APPLICATION-SPEC.md); decisions:
[INTERVIEW-LOG.md](INTERVIEW-LOG.md); what is measured: [RESULTS.md](RESULTS.md);
submission checklist: [SUBMISSION.md](SUBMISSION.md).

Status words: **done offline** = implemented and unit-tested without TigerGraph or
an LLM; **needs credentials** = cannot be done or measured without them;
**not started**.

## 1. Ordered plan

| # | Step | Status | Needs credentials? |
|---|---|---|---|
| 1 | Answer contract, trace recorder, query log, metrics, validator (`ogr.r2.output`, `trace`, `querylog`, `metrics`) | done offline | no |
| 2 | Corpus model: events, medallists, athletes, entities/facts, source records, REPORTS_ON, chunks (`corpus_model`) | done offline | no |
| 3 | GSQL: `schema_r2_answer.gsql` and ten `r2_*` queries; Python parity tools (`LocalR2Graph`) and the TigerGraph backend (`TigerGraphR2`) | done offline; GSQL never installed | install: yes |
| 4 | Agent loop, tool specs, guards (`agent`, `tools`) | done offline with a scripted model | live: yes |
| 5 | Build and run scripts: `build.sh`, `run.sh`, `r2-build`, `r2-run`, `r2-score`, `r2-metrics`; `.env.example`; `requirements.lock` | done offline | no |
| 6 | Public scorer and dev/check split (`score`, `split`, `data/public_split.json`) | done offline | no |
| 7 | Tool-level dev checks: `LocalR2Graph` reproduces 32 public answers (`tests/r2/test_dev_checks.py`) | done offline | no |
| 8 | README "Round 2 architecture" and "build, run, submit" | done | no |
| 9 | Obtain TigerGraph and LLM credentials (D6) | **blocked: not yet available** | - |
| 10 | `./build.sh corpus.jsonl`: first install of the GSQL; fix syntax and semantics errors; compare `graph_counts.json` with the offline model counts | needs credentials | yes |
| 11 | Parity check: run the ten tools on TigerGraph and on `LocalR2Graph` for the same parameters (a handful of calls per tool) and compare rows; fix differences | not started | yes |
| 12 | Smoke run: `r2-run --limit 5` on public, read the traces and the query log, check token sums | needs credentials | yes |
| 13 | Baseline on `dev` (measure tokens, latency, accuracy); decide the model (D5) | needs credentials | yes |
| 14 | Error analysis on `dev` only; fix general causes in the prompt or tools (no question-specific rules) | not started | yes |
| 15 | Run `check` once; record the result; no tuning on it after | not started | yes |
| 16 | Extend the anti-overfitting scan to `r2/`; read the code once for question wording, qids and built-in answers (rule 4) | not started | no |
| 17 | Freeze code; clean `build.sh`; `run.sh` public, then hidden, once each; `metrics.json`, query log, graph counts | not started | yes |
| 18 | Verify: validator on both answer files, query-log timestamps against traces, README accurate; tag `round2-submission`; push | not started | yes |
| 19 | Rehearse the live call: five new questions, two reproduced hidden answers | not started | yes |
| 20 | Submit the seven items by 29 Nov 23:59 IST (buffer day) | not started | - |

Suggested dates (a plan, not a record): credentials and steps 10-12 on 23-24 Nov;
13-14 on 25-26 Nov; 15-16 on 27 Nov; freeze and final runs on 28 Nov; 29 Nov is
buffer. If credentials arrive after 25 Nov the plan shrinks to steps 10-12, one
fix cycle, and the final runs; the repeatability risk then is high.

## 2. Cut order if time runs out

Lowest value per effort first: demo-only extras (three-pipeline UI, query-embedding
cache), step 14 beyond one cycle, parallel workers (keep `workers=1`). Do not cut:
step 10 (nothing runs without it), 17-18 (the deliverables), and the query log.

## 3. Open items

D5 (model), the D4 deviation confirmation, R1 ("TG Multihop30"), and the questions
to the organisers: see [INTERVIEW-LOG.md](INTERVIEW-LOG.md).

---

## Earlier plan (speculative Round 2, superseded)

Kept as history. It was written when the judged metric was assumed to be the
Agentic-vs-RAG relative gain. The code it describes (`reasoning/`, `harness/`,
`datasets/`, the P3 claim tools) exists but is not on the Round-2 answering path
(see [TECHNICAL-SPEC.md](TECHNICAL-SPEC.md) section 6).

Ordered by expected relative-accuracy gain (Agentic vs RAG) first, so the
work can ship at any stopping point. **SAFE** = additive, no schema change,
no re-ingest, no change to the Round-1 answer path. **GATED** = needs the
user's decision recorded in `INTERVIEW-LOG.md`.

**Status (2026-10-24):** steps 1–9 and 11 (offline part) are done on
`round-2`; G2 and G3 are not needed so far; G4 is allowed and not built.
Steps 0, 10, 12 and the live part of 11 need credentials (gate G5: offline
first). The commands are in `RESULTS.md` §3.

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

### Phase 6 — other enhancements, ranked

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
