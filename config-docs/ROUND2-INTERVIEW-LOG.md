# Round 2 — Interview log (Phase 3 gates)

Each gate: current state, proposed change, expected gain, cost/risk, and the
user's decision with date. Nothing gated is implemented before its decision
is recorded here.

| Gate | Topic | Decision | Date |
|---|---|---|---|
| G1 | Schema strategy and additive Round-2 types | **Option A, additive** (as proposed) | 2026-10-24 |
| G2 | Where the answer confidence comes from | **(a) agent-computed, P3 only**; shared prompt unchanged | 2026-10-24 |
| G3 | Temporal field in the LLM intent parse | **Allowed**, only if the dev split shows the deterministic detector falls short; re-baseline Round 1 if applied | 2026-10-24 |
| G4 | LLM claim extraction at ingest | **Allowed**, same condition; Round-2 datasets only, cached | 2026-10-24 |
| G5 | Credentials and run budget for measurement | **Build offline first**; live runs when credentials are added | 2026-10-24 |
| R1 | Reconcile "TG Multihop30" with the repo's eval sets | pending: question open to the user | |

## G1 — Schema strategy

- **Current:** one graph, Olympic-specific types, multi-dataset tracked only in
  `out/datasets.json`, no query scoped by dataset.
- **Proposed:** Option A (`ROUND2-ANALYSIS.md` §4): keep one graph; add
  `Dataset, Source, Entity, Claim` and the edges `IN_DATASET, ASSERTS,
  FROM_SOURCE, ABOUT, SUPERSEDES, CONTRADICTS, SAME_AS` through a
  SCHEMA_CHANGE JOB (no `DROP GRAPH`, no change to existing types); backfill
  `IN_DATASET` for Round 1 from the registry (no re-ingest, no re-embedding);
  new queries `q6_claims`, `q5s_search`; Q1–Q5 untouched.
- **Gain:** the graph pipelines can answer on a non-Olympic dataset;
  time/provenance/confidence become queryable; datasets are isolated.
- **Cost/risk:** one schema change on the live workspace (whether installed
  queries must be reinstalled after it is unverified on Savanna); about 2
  new queries to install; the backfill writes about 22k edges.

## G2 — Confidence source

- **Current:** no confidence anywhere.
- **Proposed (recommended):** (a) P3 computes it deterministically from
  claim scores (`ROUND2-DESIGN.md` §4.4), and the shared prompt is unchanged.
  Alternative (b): add `confidence` to the shared answer contract for all
  three pipelines.
- **Gain:** (a) no Round-1 change. (b) calibration is comparable across
  pipelines.
- **Cost/risk:** (a) calibration reported for P3 only. (b) the prompt changes,
  so Round-1 must be re-baselined, and verbal LLM confidence is usually poorly
  calibrated.

## G3 — Temporal field in the LLM intent parse

- **Current:** the intent schema has no time scope.
- **Proposed:** deterministic detector first (safe). Add an optional
  `temporal` field to the intent tool call only if the dev split shows
  ambiguous cases the rules miss.
- **Cost/risk:** changes the intent prompt shared by P2 and P3, so the
  Round-1 parse may shift; requires a re-baseline.

## G4 — LLM claim extraction at ingest

- **Current:** structured claims only from Olympic infoboxes.
- **Proposed:** deterministic extraction (metadata, dates, numbers, hedge
  lexicon) first. Optional one-time LLM extraction per chunk, cached by
  content hash, for prose-only datasets.
- **Gain:** claims from prose when the real dataset has no structure.
- **Cost/risk:** one-time tokens (about 1 call per chunk; for 16,669 Round-1
  chunks that is too many, so it would apply to Round-2 datasets only).

## G5 — Credentials and budget

- **Current:** this session has no `.env`; no live run is possible.
- **Needed:** TigerGraph workspace, LLM endpoint and embedding host in the
  environment's secrets; a budget for: the Round-1 baseline (100 × 3), the
  dry run (10 × 3), and the harness (dev and test splits × 3).

## R1 — "TG Multihop30"

The brief says the Round-1 trace/output schema was built against "TG
Multihop30". The repository's Round-1 sets are `eval_public.jsonl` (100) and
`eval_hidden.jsonl` (50); nothing named Multihop30 exists here.
