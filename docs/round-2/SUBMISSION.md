# Round 2 - Submission

Deadline: **29 Nov 2026, 23:59 IST**. The seven items follow the numbering of
[PROBLEM-STATEMENT.md](PROBLEM-STATEMENT.md) ("What to submit"); `data/README.md`
lists six (no repo link) and numbers the query log 5 and graph counts 6.
Nothing below has been run yet: it needs TigerGraph and LLM credentials
([PLAN.md](PLAN.md)). Paths are relative to the repository root.

## 1. The seven deliverables

| # | Deliverable | Produced by | File |
|---|---|---|---|
| 1 | Repo link with a README describing the architecture (documents to graph, tools, how the agent decides) | `README.md`, sections "Round 2: build, run, submit" and "Round 2 architecture" | repository URL at the tag |
| 2 | Answers to the 50 public questions | `./run.sh docs/round-2/data/questions_public.jsonl answers_public.jsonl` | `answers_public.jsonl` |
| 3 | Answers to the 50 hidden questions | `./run.sh docs/round-2/data/questions_hidden.jsonl answers_hidden.jsonl` | `answers_hidden.jsonl` |
| 4 | `metrics.json` for both runs | written by `run.sh` (`r2-metrics`); public block includes our accuracy and `accuracy_method`, hidden accuracy `null` | `out/r2/metrics.json` (and `metrics_notes.json`) |
| 5 | Git tag for the code that produced both answer files | `git tag round2-submission` then push the tag (by the owner, at the deadline) | tag `round2-submission` |
| 6 | TigerGraph query log of both runs | written by the run (`ogr.r2.querylog`); one file for both runs, `run_id` tells them apart | `out/r2/tg_query_log.jsonl` |
| 7 | Vertex and edge counts by type after loading `corpus.jsonl` | `./build.sh docs/round-2/data/corpus.jsonl` | `out/r2/graph_counts.json` |

`out/` is git-ignored: copy items 4, 6 and 7 into the submission package
separately. If the metrics `cost_usd_total` should be real, set
`R2_LLM_INPUT_USD_PER_M` and `R2_LLM_OUTPUT_USD_PER_M` before the runs.

## 2. Pre-submission checklist

Tick each only when done and verified.

**Environment**
- [ ] TigerGraph workspace and LLM credentials available; `.env` filled from `.env.example` (every key).
- [ ] Clean environment: `python3 -m pip install -r backend/requirements.lock && python3 -m pip install --no-deps -e backend`.
- [ ] Model chosen and recorded (D5); prices set if cost is to be reported.
- [ ] `cd backend && python3 -m pytest -q` passes (and `ruff check src tests`).

**Build**
- [ ] `./build.sh docs/round-2/data/corpus.jsonl` completes (first live install of the GSQL).
- [ ] `out/r2/graph_counts.json` exists and is plausible against the offline model (3,530 Document vertices; Athlete, WON, SourceRecord (39), REPORTS_ON, Entity, Claim non-zero). Expected values are not recorded anywhere yet; derive them from `build_model` and compare.
- [ ] Parity spot check: each tool on TigerGraph and `LocalR2Graph` for the same parameters.

**Development runs (not the submission)**
- [ ] Smoke run `r2-run --limit 5`; read the traces; validator clean.
- [ ] Public run, then score: `out/r2/score_public.json`; compute accuracy on `dev` and `check` from `docs/round-2/data/public_split.json`.
- [ ] Error analysis on `dev` only; fix general causes; `check` looked at once.
- [ ] Rule 4 review: no regex on question wording, no qids, no answers in `backend/src/ogr/r2/`; extend `tests/pipelines/p3/test_anti_overfitting.py` to `r2/`.

**Final runs (same code, same settings)**
- [ ] Code frozen and committed; working tree clean.
- [ ] Delete `answers_public.jsonl`, `answers_hidden.jsonl`, `out/r2/tg_query_log.jsonl`, `out/r2/metrics.json` (`r2-run` skips qids already in the file; the log is append-only).
- [ ] `./build.sh docs/round-2/data/corpus.jsonl` from scratch.
- [ ] `./run.sh docs/round-2/data/questions_public.jsonl answers_public.jsonl`.
- [ ] `./run.sh docs/round-2/data/questions_hidden.jsonl answers_hidden.jsonl` (once; the hidden file is only read by the system).
- [ ] 50 lines in each answers file; no qid missing (a failed question is not written; `r2-run` exits 1 and says which).

**Verification**
- [ ] Validator output empty for both files (`r2-metrics` prints errors and warnings to stderr): token sums equal, steps numbered, TigerGraph steps have query, params, rows.
- [ ] Every answer has a TigerGraph step (`answers_with_tigergraph_step` = 50 in both blocks); none produced with `--backend local`.
- [ ] Query-log timestamps fall inside the matching traces (spot check several qids; log `ts` is a call's start in UTC).
- [ ] `metrics.json` has both blocks, all fields; hidden `accuracy_pct` is `null`.
- [ ] README accurate against the code (see the inconsistencies in [RESULTS.md](RESULTS.md) section 4).
- [ ] Tag `round2-submission` on the committed code; pushed.
- [ ] Package assembled: repo link, two answer files, `metrics.json`, query log, graph counts; sent before the deadline.

## 3. For the live judging call

Judges will ask new questions and pick hidden questions to reproduce, with
TigerGraph running and the full corpus loaded.

Have ready before the call:
- TigerGraph workspace running and loaded (`graph_counts.json` matches the live counts); `.env` in place; the tagged commit checked out; backend installed.
- The exact model and settings used for the final runs; the same `R2_MAX_STEPS`.
- Terminal with `./run.sh` usable on a one-question file, and `python3 -m ogr.cli r2-run --questions q.jsonl --out live.jsonl --qids <qid>` for a single qid (use a fresh output file; reruns skip existing qids).
- Submitted `answers_hidden.jsonl` and the query log open, to compare a reproduced answer and trace with the submitted ones.
- README "Round 2 architecture", `SOLUTION-DESIGN.md`, and `backend/src/ogr/r2/agent.py` (system prompt) and `tools.py` (tool list) open for the architecture talk.
- One trace of each kind to walk through: a list or count answer, a source-conflict answer (authority and time), a `partial`, a `not_in_corpus`.
- The graph schema in `backend/src/ogr/graph/schema_r2_answer.gsql` and one query such as `r2_medals_by_nation.gsql`.
- The honest limits: public accuracy is our own proxy score; the check split is small; source records are weighed by the LLM at answer time (D4 deviation); model output is not guaranteed identical between runs.
- A list of 5-10 new questions of our own, written per question style, kept outside the code.
