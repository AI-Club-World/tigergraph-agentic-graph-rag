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
| D1 | Answer policy | **(b) allow `partial` and `not_in_corpus`**, driven by structured evidence; supersedes "always commit" | 2026-11-23 |
| D2 | Three-pipeline comparison | **(b) demo only**, not in `run.sh` | 2026-11-23 |
| D3 | Schema additions | **(c) Athlete/WON plus generic Entity/Claim for every infobox type** | 2026-11-23 |
| D4 | Claim extraction from prose at ingest | **(a) as recommended, then changed in implementation**: no LLM at build (see "Deviation from D4") | 2026-11-23 |
| D5 | LLM and model for the run | **Decide after a measured baseline**; not decided | 2026-11-23 |
| D6 | Credentials timing | **Obtain TigerGraph and LLM credentials immediately** | 2026-11-23 |
| D7 | Dev set versus held-out check | **Split the public 50 by style; freeze `check` until the end** | 2026-11-23 |

D1-D7 come from [BRIEF-ANALYSIS.md](BRIEF-ANALYSIS.md) section 6 and were
accepted as recommended on 2026-11-23, with the one implementation deviation
recorded under D4 below. The gates above (G1-G5, 2026-10-24) were made for the
speculative Round 2 and are kept as history; where they conflict with D1-D7,
D1-D7 apply.

## G1 — Schema strategy

- **Current:** one graph, Olympic-specific types, multi-dataset tracked only in
  `out/datasets.json`, no query scoped by dataset.
- **Proposed:** Option A (`ANALYSIS.md` §4): keep one graph; add
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
  claim scores (`DESIGN.md` §4.4), and the shared prompt is unchanged.
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


## Round-2 decisions on the real brief (2026-11-23)

Context: the real brief ([PROBLEM-STATEMENT.md](PROBLEM-STATEMENT.md),
[data/README.md](data/README.md)) scores one system's hidden-set answers fact by
fact, with statuses `answered`, `partial` and `not_in_corpus`. The gap analysis
is [BRIEF-ANALYSIS.md](BRIEF-ANALYSIS.md); the resulting build contract is
[SOLUTION-DESIGN.md](SOLUTION-DESIGN.md). The owner accepted D1-D7 as
recommended.

**Superseded answer policy.** The earlier policy, "always commit to one best
answer with a confidence and the conflicting values cited; no abstention"
(recorded in `DESIGN.md` and the old `APPLICATION-SPEC.md`), is superseded by
D1. The system now answers `not_in_corpus` when the corpus does not answer, and
`partial` when part is missing.

### D1 - Answer policy
Allow `partial` and `not_in_corpus`, decided from structured evidence rather
than from a score threshold. Reason: the brief scores both statuses plus 10%
honesty, and an invented answer to an unanswerable question scores 0; "always
commit" gives up the 4 `not_in_corpus` public questions and the honesty weight.
Consequence: the answer contract gains a `status` field. Risk: over-abstention
lowers accuracy; the abstention rules in the prompt are general, and the
`check` split (D7) is where that is looked at.

### D2 - Three-pipeline comparison
Keep it as a demo aid only; it is not part of `run.sh` and not a judged
criterion. The relative-gain targets of the earlier application spec are
dropped.

### D3 - Schema additions
Option (c): add `Athlete` and `WON` edges, plus a generic `Entity`/`Claim` for
every non-Olympic infobox (film, office holder, person), reusing the Entity and
Claim types of the earlier fact layer. One schema change on the workspace, in
`schema_r2_answer.gsql`. Not yet installed on a live workspace.

### D4 - Claim extraction from prose at ingest
Accepted: LLM extraction for the 39 source records and the 127 LA 2028 articles,
cached in a committed file, deterministic parsing for the rest.

**Deviation from D4 (implementation, 2026-11-23).** Source records are not
LLM-extracted at build. Their authority class and publication time are computed
deterministically from their `Source:` and `Published:` lines (a general lexicon
over the source name; `ogr.r2.corpus_model`). Each record is stored as a
`SourceRecord` vertex and linked to the LA 2028 events it mentions by
`REPORTS_ON`. The answering LLM reads the records through the `source_records`
tool and weighs them using the authority and time fields. Reason: a cheaper
build and a reproducible one (no LLM at `build.sh`, no cache to commit, nothing
to drift between builds). Cost: reliability judgements happen at answer time, so
they are repeated per question and their quality depends on the model. The 127
LA 2028 articles are read as text (`text_search`, `read_document`), not
extracted. This deviation needs the owner's confirmation; it is recorded here so
the log matches the code.

### D5 - LLM and model for the run
Decide after the first measured baseline (tokens per question with the default
model); not chosen by assumption. Open. `.env.example` still carries the
Round-1 default model; no Round-2 model has been measured.

### D6 - Credentials timing
Obtain TigerGraph and LLM credentials immediately. Nothing about accuracy,
tokens, latency or the query log can be measured without them. At the time of
writing they are not available in the build environment.

### D7 - Dev set versus held-out check
Split the public 50 by answer shape and status (not question wording) into `dev`
and `check`; develop on `dev`, freeze `check` until the end, and report both in
`accuracy_method`. Implemented as `ogr.r2.split`; the split is committed in
`data/public_split.json` (36 dev, 14 check). Final public accuracy is still
reported on all 50, as the brief requires. The hidden questions are not read by
anyone working on the system.

### Still open
- **R1 - "TG Multihop30"**: still pending. Nothing by that name exists in this
  repository; the Round-1 sets are public-100 and hidden-50.
- D5 (model choice) and the owner's confirmation of the D4 deviation.
- Questions to the organisers (BRIEF-ANALYSIS section 8), notably how list/JSON
  answers are scored and what query log is acceptable on a managed workspace.
