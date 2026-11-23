# Round 2 — Application spec

Round-2 statement (verbatim): *"Extend your agent to reason over evolving,
conflicting, and uncertain facts on a harder dataset."*

This extends the Round-1 application spec
([../round-1/APPLICATION-SPEC.md](../round-1/APPLICATION-SPEC.md)), whose
FR/NFR still hold. Companion documents in this folder:
[ANALYSIS.md](ANALYSIS.md), [DESIGN.md](DESIGN.md), [PLAN.md](PLAN.md),
[INTERVIEW-LOG.md](INTERVIEW-LOG.md), [RESULTS.md](RESULTS.md),
[ARCHITECTURE-SPEC.md](ARCHITECTURE-SPEC.md),
[TECHNICAL-SPEC.md](TECHNICAL-SPEC.md).

Status: built and tested offline on `round-2`; **not measured live**. The
Round-2 problem statement and dataset have not been released yet; every
statement about them below is an assumption until they are.

| Field | Value |
|---|---|
| Research thesis (to be measured) | When facts change, sources disagree or statements are hedged, top-k retrieval hands the model several values and no rule for choosing. An agent that stores each statement as a claim (who said it, when, how firmly) can choose by an inspectable rule, keep the losing values as evidence, and say how sure it is. The extra work is a graph query and arithmetic, not extra LLM calls |
| Judged (as known) | Relative accuracy improvement of Agentic GraphRAG over plain RAG, architecture, agent design, token efficiency, engineering quality |

## 1. Judging criteria and the evidence for each

"Measured" means a recorded live run. "Offline" means tests or the
component-level harness, without TigerGraph or an LLM. Nothing in the
Round-2 column is a live pipeline result yet.

| Criterion | Round-1 evidence (measured, run `r5-public`) | Round-2 evidence | Gap to close |
|---|---|---|---|
| Relative accuracy, Agentic vs RAG | EM 0.98 vs 0.59 (+0.39); right on 39 questions RAG misses, wrong on none RAG gets right | Offline only: the resolver picks the true value on 0.89–0.94 of harness test questions (oracle parse); no RAG comparison | **Live harness run, three pipelines** (§12 step 5). This is the judged number and it does not exist yet |
| Architecture | One graph holds entities, chunks and vectors; five installed GSQL queries; shared dispatcher for UI and batch | Additive fact layer (`Dataset, Source, Entity, Claim`), dataset-scoped search, adapters per dataset; Round-1 types and queries untouched | First install on Savanna (§12 step 2) |
| Agent design | Deterministic router, evidence check, fallbacks, closed stop vocabulary, answer verification | Claim probe decides whether claims matter; temporal scope, supersession and conflict resolution are deterministic and written to the trace; one corroborating search on a narrow margin; ask-back when the question is ambiguous | Show it on the trace panel in the demo (§4, US-R2-1 to US-R2-4) |
| Token efficiency | Median 2,550 tokens vs RAG 6,453; 62 of 100 questions take the direct route | No new LLM calls: the claims route replaces the groundedness call with arithmetic | Tokens per question on the harness (§12 step 5) |
| Engineering quality | `make reproduce`; deterministic scorer; anti-overfitting tests | 693 backend and 63 frontend tests; dev/test split with weights frozen before test; gate log for every schema or model decision | Round-1 regression re-run on `round-2` (§12 steps 1 and 6) |
| Honesty of claims | A question type reported where the agent is not worth it (lookup) | Limits listed in [RESULTS.md](RESULTS.md) §4, including where the resolver stops working | Keep every Round-2 number tied to a run file |

## 2. Scope decisions

| Decision | Resolution | Basis |
|---|---|---|
| Round-2 schema | One graph, additive fact layer, datasets scoped by `IN_DATASET` (gate G1, owner's decision 2026-10-24) | A separate graph per dataset would duplicate the embedding types and break the max-two-models design |
| Round-2 confidence | Computed by the agent from the weighed claims, for Agentic GraphRAG only; the shared answer prompt is unchanged (gate G2) | Round-1 results stay comparable; a model's stated confidence is usually poorly calibrated |
| Round-2 answer policy | Always commit to one best answer, with a confidence and the conflicting values cited; no abstention | Owner's decision |

## 3. Requirements (statement: "Extend your agent to reason over evolving, conflicting, and uncertain facts on a harder dataset")

EARS notation. "Built" means implemented and tested offline; see
[RESULTS.md](RESULTS.md) for the offline figures and their limits.

| Id | Requirement | Status |
|---|---|---|
| R2-FR-1 | When a question puts a time scope on a fact ("as of", "originally", "latest", before/after a revision), the agent shall answer with the value known and valid in that scope. Edition-relative wording ("the Games before 2016") shall not count as a time scope | Built; offline evolving 1.00 (oracle parse); no Round-1 question is time-scoped |
| R2-FR-2 | When sources state different values, the agent shall choose one by an inspectable score (reliability, corroboration, recency, extraction, hedging) and cite the losing values | Built; offline conflicting 0.83–1.00 by difficulty and by what is known about the sources |
| R2-FR-3 | The agent shall give a confidence with each claims-based answer, calibrated on held-out questions; it shall not abstain by default | Built (Agentic only, gate G2) |
| R2-FR-4 | When a later statement revises an earlier one, the earlier one shall be kept as superseded evidence, not deleted; a hedged statement shall not supersede a firm one | Built |
| R2-FR-5 | A new dataset shall plug in through an adapter without changes to the reasoning code | Built (`datasets/`); real format unknown |
| R2-FR-6 | Where several datasets are loaded, a run shall be able to restrict retrieval to named datasets, so that test or Round-2 data cannot change Round-1 results | Built in code (`IN_DATASET`, Q5S, Q6 dataset filter); **not yet exposed** as a run or UI setting |
| R2-FR-7 | The system shall generate a validation set of evolving, conflicting and uncertain facts with known ground truth, parameterised by difficulty, conflict rate, hedging, noise and source information, deterministic for a seed, split by event into dev and test | Built (`ogr.cli harness`) |
| R2-FR-8 | For every claims-based answer the record shall carry the time scope, the chosen value, each alternative with its score terms and sources, and the superseded values; the UI shall show them | Built (`confidence`, `temporal_scope`, `conflicts`, `TraceStep.details`) |
| R2-FR-9 | When the chosen value's share of the weight is below the margin, the agent shall run one corroborating search and then commit | Built (margin 0.6, one search) |
| R2-FR-10 | When the model's answer names a value the resolution ranked lower, the resolved value shall stand and the trace shall say so | Built |
| R2-FR-11 | Where a dataset states facts only in prose, the system shall extract claims at ingest, once, with the result cached | **Not built** (allowed by gate G4). Until then such a dataset reaches only RAG and the prose fallbacks |
| R2-FR-12 | The dashboard shall report the Round-2 subsets beside the Round-1 types, and show confidence calibration for the agentic pipeline | Subsets: built. Calibration view: **not built** (figures are in the CLI report) |
| R2-NFR-1 | Round-1 behaviour shall not regress: unchanged routes when no claims matter, unchanged shared answer prompt, unchanged Q1–Q5 | Offline suite passes; live baseline not yet re-run |
| R2-NFR-2 | Same LLM and embedding model in all three pipelines; tokens per question reported; agent loops bounded (`RUN_MAX_STEPS`, `RUN_MAX_TOKENS_PER_QUERY`, one corroborating search); no LLM call added by Round 2 | Built; tokens not yet measured |
| R2-NFR-3 | No schema change, re-ingest or provider change without the owner's confirmation | Gates logged in [INTERVIEW-LOG.md](INTERVIEW-LOG.md) |
| R2-NFR-4 | Weights, calibration and thresholds shall be fitted on the dev split only and frozen before the test split is run; nothing shall be derived from questions or gold answers | Built (`harness --offline`, `OGR_ROUND2_WEIGHTS`) |
| R2-NFR-5 | The validation set shall not weaken RAG artificially, and generated statements about real people shall be neutral | Built; a test rejects accusatory wording |
| R2-NFR-6 | Conflict resolution shall be deterministic: the same claims give the same answer, confidence and trace | Built and tested |

## 4. User stories

| ID | Story | Acceptance |
|---|---|---|
| US-R2-1 | As a judge, I ask who holds a result "as of 2015", "originally" and "currently", and get three different, correct answers, each with the superseded values shown | R2-FR-1, R2-FR-4, R2-FR-8 |
| US-R2-2 | As a judge, I ask a question where a blog and an official source disagree, and see which value was chosen, the score behind it, and the losing value still cited | R2-FR-2, R2-FR-8 |
| US-R2-3 | As a judge, I ask a question whose only support is a hedged report, and the answer comes with a visibly low confidence instead of false certainty | R2-FR-3 |
| US-R2-4 | As a judge, I see on the trace that the conflict was settled by a graph query and a deterministic score, and how many tokens that cost next to RAG | R2-FR-8, R2-NFR-2 |
| US-R2-5 | As a judge, I ask an ambiguous question and the agent asks back with the candidates instead of guessing | Round-1 FR-25 |
| US-R2-5 | As the team, we plug in the real Round-2 dataset by writing one adapter, and rerun the same harness commands | R2-FR-5, R2-FR-7 |

## 5. Success criteria (targets; none measured live yet)

The judged quantity is the relative gain of Agentic GraphRAG over plain RAG.
Targets are set before the run so the result cannot move them. They apply
to the harness **test** split (weights fitted on dev only) until the real
Round-2 dataset replaces it.

| Criterion | Target | Status |
|---|---|---|
| Relative accuracy gain | Agentic − RAG EM ≥ +0.25 on each of the evolving, conflicting and uncertain subsets, reported with Wilson 95% intervals, absolute and relative | Not measured |
| The loop's own contribution | Agentic − GraphRAG reported per subset, whatever its sign | Not measured |
| Token efficiency | Agentic median tokens per question ≤ RAG's on the same questions; tokens per correct answer reported for all three | Not measured |
| Calibration | Agentic ECE ≤ 0.10 and Brier reported on test; reliability table in the report | Offline (oracle parse): ECE 0.01–0.09 overall; uneven per subset |
| Unanswerable items | Mean confidence on unanswerable items lower than on answerable ones | Not measured |
| Round-1 regression | Public-100 on `round-2` after the fact layer is installed: Agentic EM not below the same-day baseline by more than one question; RAG unchanged | Offline suite passes; live run not done |
| Fair baseline | Same documents, `k`, LLM, embedding model and answer prompt in all three pipelines; source and date visible in the text RAG retrieves | Built into the harness |
| Reproducibility | One command generates the harness, one fits and reports offline, one batch command per live run; seed and parameters recorded in the manifest | Built |
| Real dataset | Loaded through an adapter with no change to the reasoning code; every [ASSUMPTION] in the Round-2 documents reconciled | Dataset not released |

## 6. Risks to the Round-2 result

| Risk | Likelihood | Effect | Mitigation |
|---|---|---|---|
| No live Round-2 measurement before the deadline | High until credentials are added | No judged number at all | §12 steps 1–5 first, before any further feature |
| The fact-layer GSQL fails on first install | Medium (never run on Savanna) | Blocks every live Round-2 run | Install early; the job is additive and Q1–Q5 keep working if it fails |
| The real dataset is prose-only | Unknown | Graph pipelines have no claims; the gain over RAG shrinks to Round-1 behaviour | Build R2-FR-11 as soon as the format is known |
| The real dataset is not about Olympic events | Unknown | Subjects must link as generic entities; entity linking for them is untested | `Entity` type and `ent:` subjects exist; test on the first sample |
| The intent parse misses the subject or attribute on Round-2 wording | Medium | The resolver never runs, however good it is | Dry run first; gate G3 allows a temporal field in the parse if the rules fall short |
| Evolving cases in the harness are too easy | Known | An inflated evolving score that will not transfer | Harder generator before the reported run |
| RAG scores well on the harness because source and date are in its text | Medium | Smaller gain | Report it as it is; the comparison stays fair |
| Round-1 score moves after the fact layer is installed | Low | Regression in a judged Round-1 criterion | Same-day baseline before and after |

## 7. Readiness checklist (in order; stop anywhere and the work before it stands)

| # | Step | Needs | Status |
|---|---|---|---|
| 1 | Round-1 baseline on `round-2`: public-100, three pipelines | Credentials | Not done |
| 2 | Install the fact layer and backfill claims (`ogr.cli round2`); reinstall Q2/Q3 | Credentials | Not done |
| 3 | Build the harness corpus as its own dataset | Step 2 | Not done |
| 4 | Dry run: 10 questions × three pipelines; read the cost before going on | Step 3 | Not done |
| 5 | Harness test split × three pipelines; per-subset report with intervals, tokens and calibration | Step 4 | Not done |
| 6 | Round-1 regression after the fact layer | Step 2 | Not done |
| 7 | Expose the dataset scope as a run setting (R2-FR-6) | – | Not done |
| 8 | Harder evolving generator | – | Not done |
| 9 | Score the paraphrase set; rerun the hidden set on the final system | Credentials | Not done |
| 10 | Calibration view on the dashboard (R2-FR-12) | Step 5 | Not done |
| 11 | Demo script with one question each for US-R2-1 to US-R2-5 | Step 5 | Not done |
| 12 | Real dataset: adapter, reconcile assumptions, rerun steps 3–6 | Dataset release | Blocked |

## 8. Open questions

| Question | Status |
|---|---|
| Round-2 dataset format, guidebook and deadline | **Open** — not released. The generic adapter and the class reliability priors are labelled assumptions |
| "TG Multihop30" | **Open** — the Round-2 brief says the Round-1 output format was built against it; nothing by that name is in this repository (the Round-1 sets are public-100 and hidden-50) |
| Does the real dataset say anything about its sources? | **Open** — with no reliability information and a coordinated false majority, the resolver's offline accuracy on conflicting items stops near 0.83 |
