# Round 2 - Application spec

Round-2 brief: build an agentic GraphRAG system on TigerGraph that reasons across
many documents, weighs sources that disagree, and says honestly what cannot be
established. Brief: [PROBLEM-STATEMENT.md](../../round-2/PROBLEM-STATEMENT.md),
[data/README.md](../../round-2/data/README.md). Gap analysis: [BRIEF-ANALYSIS.md](BRIEF-ANALYSIS.md).
Build contract: [SOLUTION-DESIGN.md](../../round-2/SOLUTION-DESIGN.md). Owner decisions D1-D7:
[INTERVIEW-LOG.md](INTERVIEW-LOG.md). Companion documents:
[ARCHITECTURE-SPEC.md](../../round-2/ARCHITECTURE-SPEC.md), [TECHNICAL-SPEC.md](../../round-2/TECHNICAL-SPEC.md),
[PLAN.md](PLAN.md), [RESULTS.md](RESULTS.md), [SUBMISSION.md](../../round-2/SUBMISSION.md).
Round-1 requirements ([../round-1/APPLICATION-SPEC.md](../../round-1/APPLICATION-SPEC.md))
still apply to the Round-1 code, which Round 2 does not change.

Status (2026-11-23): the system is built on branch `round-2` and tested offline.
**Nothing has run against TigerGraph or an LLM**, so there is no measured
accuracy, token, latency or cost figure. Every number in section 5 is a target.

**Superseded.** The earlier version of this spec assumed the judged metric was the
relative gain of Agentic GraphRAG over plain RAG, with an "always answer, never
abstain" policy, and tested on a synthetic harness. The real brief scores one
system's absolute hidden-set answers and scores `not_in_corpus` and `partial`
explicitly, so the relative-gain targets and the no-abstention policy are dropped
(decisions D1 and D2). The synthetic-harness requirements (R2-FR-1 to R2-FR-12,
R2-NFR-1 to R2-NFR-6 of that version) are superseded; that work is kept as
earlier work in [RESULTS.md](RESULTS.md) section 5 and
[TECHNICAL-SPEC.md](../../round-2/TECHNICAL-SPEC.md) section 6, and is not on the answering path.

## 1. Judging criteria and the evidence for each

"Evidence" is what we will be able to show; "Status" says whether it exists.

| Criterion (weight) | Evidence / plan | Status |
|---|---|---|
| Hidden-set accuracy (40%, organisers' key, fact by fact) | Structured answers (text or JSON, complete lists); ten graph tools; own fact-level scorer on the public 50 as a proxy (`ogr.r2.score`); `check` split held out | Tool-level checks pass offline (32 public answers reproduced by `LocalR2Graph`); accuracy not measured |
| Honesty (10%) | Three statuses; `not_in_corpus` forces a null answer; prompt rules: unknown is not negative, never guess | Built; not measured |
| Evidence (10%) | `citations` limited to doc_ids that tools returned; prompt asks for the doc_ids that support each fact | Built; citation precision not measured (public `gold_doc_ids` allow it) |
| Repeatability (15%) | `build.sh` / `run.sh`, `backend/requirements.lock`, `.env.example`, traces written as the code runs, query log, token-sum and step-time checks, graph counts, git tag | Scripts and writers built; no live run, so no log to compare with traces yet |
| Efficiency (10%) | Per-question tokens, latency, LLM calls and TigerGraph queries in `metrics.json`; `R2_MAX_STEPS` bounds tool calls; no embeddings at answer time | Counters built; values unknown until the first run (model choice D5 open) |
| Live judging (15%) | README "Round 2 architecture"; the trace of every answer; a prepared live-call kit in [SUBMISSION.md](../../round-2/SUBMISSION.md) | README written; demo not rehearsed on a live system |

## 2. Scope decisions

| Decision | Resolution | Basis |
|---|---|---|
| Answer policy | `answered`, `partial` or `not_in_corpus`, from structured evidence; never an invented answer | D1 (replaces "always commit") |
| Three-pipeline comparison | Demo only; not in `run.sh`, not a criterion | D2 |
| Schema | Additive: Athlete, WON, SourceRecord, REPORTS_ON, Entity/Claim infobox facts | D3 |
| Source records | Authority and publication time computed deterministically at build; the answering LLM weighs them (deviation from D4) | INTERVIEW-LOG |
| Model for the run | Not chosen; decide after a measured baseline | D5 |
| Dev/check split | Public 50 split by answer shape; `check` frozen until the end | D7 |

## 3. Requirements

EARS notation. Ids R2B-* are the requirements for the real brief. "Built" means
implemented and unit-tested offline.

| Id | Requirement | Status |
|---|---|---|
| R2B-FR-1 | The system shall answer a natural-language question by planning its own steps, calling graph tools and returning one answer record per question | Built (`ogr.r2.agent`) |
| R2B-FR-2 | The answer record shall carry `status` in {`answered`, `partial`, `not_in_corpus`}. When the status is `not_in_corpus` the answer shall be null | Built (guard in `_finalize`; validated in `ogr.r2.output`) |
| R2B-FR-3 | When part of a question is not in the corpus, the system shall give status `partial`, answer what the corpus supports and say what is missing | Built (prompt); not measured |
| R2B-FR-4 | The `answer` shall be text or JSON; lists shall be complete | Built (prompt asks for it); not measured |
| R2B-FR-5 | `citations` shall contain only doc_ids returned by a tool during that question | Built (guard) |
| R2B-FR-6 | When sources differ, the system shall prefer the more authoritative source (official > operational > secondary > unreliable), separate effective time from publication time, and state what was provisional, superseded or unconfirmed | Built as data (authority, publication time) plus prompt rules; quality depends on the model, not measured |
| R2B-FR-7 | The system shall use TigerGraph when answering: every retrieval tool is one installed GSQL query | Built; never installed on a live workspace |
| R2B-FR-8 | Every answer shall carry a trace written as the code runs: per step `step, tool, tigergraph, ms`, plus `query, params, rows` for TigerGraph steps and `input_tokens, output_tokens` for LLM steps. Answer token totals shall equal the sum over LLM steps | Built (`ogr.r2.trace`, `validate`) |
| R2B-FR-9 | Every TigerGraph call shall be appended to a query log with a start timestamp, qid, step, query, params, rows, ms and ok | Built (`ogr.r2.querylog`) |
| R2B-FR-10 | The system shall write `metrics.json` for both sets from the answer files only, with every field of the brief's example | Built (`ogr.r2.metrics`) |
| R2B-FR-11 | The system shall write vertex and edge counts by type after the build | Built (`graph_counts.json`); needs a live server |
| R2B-FR-12 | One-command build and run: `./build.sh corpus.jsonl`, `./run.sh questions answers` | Built |
| R2B-FR-13 | Dependencies shall be locked (`backend/requirements.lock`) and every key listed in `.env.example` | Built; lock resolved but not installed from scratch in this environment |
| R2B-FR-14 | The system shall contain no question-specific rules: no regex on question wording, no qids, no answers in code. The prompt and tools shall be general | Built by design. The Round-1 scan (`tests/pipelines/p3/test_anti_overfitting.py`) lists only `pipelines/` and `graph/` as answer path, so `r2/` is not in that list; extend it or review `r2/` by hand before tagging |
| R2B-FR-15 | The system shall answer questions it has not seen and reproduce a submitted hidden answer and its trace on request | Not demonstrated; needs a live run |
| R2B-FR-16 | The system shall report a public self-score by a stated method, without reading the hidden questions' answers (there are none) | Built (`ogr.r2.score`, `accuracy_method`) |
| R2B-NFR-1 | The build shall need no LLM and no embedding model; `run.sh` shall need an LLM and TigerGraph only | Built |
| R2B-NFR-2 | Behaviour shall be deterministic where possible: temperature 0, stable ordering, bounded steps (`R2_MAX_STEPS`, default 8) | Built; model output is still not guaranteed identical |
| R2B-NFR-3 | A failed question shall not stop the run and shall not be written as an answer; a rerun retries it | Built (`run_questions` skips only qids already in the file) |
| R2B-NFR-4 | Round-1 code paths and the offline suite shall not regress | Offline suite passes (920 tests, owner-reported) |
| R2B-NFR-5 | The local backend (`--backend local`) shall be dev only: its steps are `tigergraph: false` and write no query log | Built |

## 4. User stories (live judging)

| ID | Story | Acceptance |
|---|---|---|
| US-R2B-1 | A judge asks a new list or count question; the trace shows graph queries and a complete, cited answer | R2B-FR-1, 4, 5, 7, 8 |
| US-R2B-2 | A judge asks about a result that was provisional, then decided; the answer names the official source and time, and says why the other documents differ | R2B-FR-6 |
| US-R2B-3 | A judge asks something the corpus does not contain; the answer is `not_in_corpus` with no invented content | R2B-FR-2 |
| US-R2B-4 | A judge picks a hidden question; the system reproduces the submitted answer and trace shape | R2B-FR-15 |
| US-R2B-5 | A judge asks how it decides; we show the prompt, the tool list and one trace | README |

## 5. Success criteria (targets, not results)

Set before any run so that results cannot move them. Accuracy targets use our own
scorer on the public questions, the `check` split (14 questions) and all 50, and
are proxies for the organisers' key.

| Criterion | Target | Status |
|---|---|---|
| Public accuracy, `check` split | Report `accuracy_pct` for `check` and for all 50 with `accuracy_method`; aim for the `check` score within 10 points of the `dev` score (no overfitting to dev). No absolute target is set because the organisers' scale is unknown | Not measured |
| Honesty on public | All 4 gold `not_in_corpus` questions answered `not_in_corpus`; no `not_in_corpus` on a question with a gold answer unless the gold status is `partial` | Not measured |
| Statuses | Status matches gold on at least 90% of the public 50 | Not measured |
| Citations | Every answer cites at least one doc_id; compare with public `gold_doc_ids` and report precision and recall | Not measured |
| Trace integrity | 0 errors from `validate` on every answer; token sums equal; at least 95% of answers have a TigerGraph step; every TigerGraph step has a query-log line within the step's time window | Checked offline on scripted runs only |
| Efficiency per question | Targets are examples from the brief's sample (about 2-3 LLM calls, about 3 TigerGraph queries, about 3-4k tokens per question); the real values are reported, not forced. A question that hits the step budget is read in the trace | Not measured |
| Run time | Public and hidden run each within the time of one demo-length session; report `total_run_time_s` | Not measured |
| Reproducibility | A clean clone builds and runs from `build.sh` / `run.sh` with only `.env` filled in; two runs of the public set differ only by model non-determinism, which is reported | Not demonstrated |

## 6. Risks

| Risk | Likelihood | Effect | Mitigation |
|---|---|---|---|
| No live measurement before the deadline (no credentials yet) | High until credentials are added | No accuracy or efficiency evidence; first install of the GSQL is its first syntax check | Obtain credentials first (D6); install and run the dry run before anything else ([PLAN.md](PLAN.md)) |
| GSQL queries fail on first install | Medium | Blocks every live run | Install early; 227 offline tests cover the Python side and a static GSQL check |
| The model over- or under-abstains | Medium | Lower accuracy or honesty | Look at `check` once; adjust general prompt rules only |
| Model does not support native tool calling or does not report token usage | Medium | Agent loop fails, or tokens are estimated | `LLM_SUPPORTS_TOOL_CALLING`, `LLM_REPORTS_TOKEN_USAGE`; estimated tokens are marked in the trace `note` |
| Source-record weighing is left to the LLM (D4 deviation) | Medium | Inconsistent answers on conflicting-source questions | Authority and time are given as fields; compare the public source-record questions |
| Rerun with the same output file skips answered qids | Certain | A stale file mistaken for a fresh run | Delete answer files, query log and `out/r2/` before the final runs ([SUBMISSION.md](../../round-2/SUBMISSION.md)) |
| A hidden answer cannot be reproduced live (model drift) | Medium | Repeatability and disqualification risk | Temperature 0, same model and settings, keep the traces; rehearse reproduction |

## 7. Open questions

| Question | Status |
|---|---|
| Model and provider for the run (D5) | Open; decide after a measured baseline |
| Owner's confirmation of the D4 deviation (no LLM extraction of source records at build) | Open |
| "TG Multihop30" (R1) | Open; nothing by that name in this repository |
| How the organisers score list/JSON answers, what query log is acceptable on a managed workspace, whether overridden documents must be cited | Open; questions to the organisers (BRIEF-ANALYSIS section 8) |
