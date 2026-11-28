# Round 2 - Submission

Deadline: **29 Nov 2026, 23:59 IST**. The seven items follow the numbering of
[PROBLEM-STATEMENT.md](PROBLEM-STATEMENT.md) ("What to submit"); the organisers'
`data/README.md` lists six (no repo link) and numbers the query log 5 and the graph
counts 6. Paths are relative to the repository root. How to run each step is in the
README, section "Round 2: build, run, submit".

## 1. The seven deliverables

| # | Deliverable (as the brief states it) | Produced by | File |
|---|---|---|---|
| 1 | Repo link, with a README describing the architecture: how documents become graph data, which tools the agent has, how it decides what to do next | `README.md`, sections "Architecture", "Round 2: build, run, submit" and "Round 2 architecture" | the repository URL, at the tag |
| 2 | `answers_public.jsonl`: answers to the 50 public questions | `./run.sh docs/round-2/data/questions_public.jsonl answers_public.jsonl` | `answers_public.jsonl` |
| 3 | `answers_hidden.jsonl`: answers to the 50 hidden questions | `./run.sh docs/round-2/data/questions_hidden.jsonl answers_hidden.jsonl` | `answers_hidden.jsonl` |
| 4 | `metrics.json`: a summary of both runs | written by `run.sh` (`r2-metrics`); the public block includes our accuracy and `accuracy_method`, hidden accuracy is `null` | `out/r2/metrics.json` (and `metrics_notes.json`) |
| 5 | A git tag on the repo for the code that produced both answer files | `git tag round2-submission`, then push the tag | tag `round2-submission` |
| 6 | The TigerGraph query log from both runs, timestamps matching the traces | written by the run (`ogr.r2.querylog`); one file for both runs, `run_id` tells them apart | `out/r2/tg_query_log.jsonl` |
| 7 | Vertex and edge counts by type after loading `corpus.jsonl` | `./build.sh docs/round-2/data/corpus.jsonl` | `out/r2/graph_counts.json` |

Each answer line has `qid`, `status` (`answered`, `partial`, `not_in_corpus`), `answer`,
`explanation`, `citations`, `input_tokens`, `output_tokens`, `latency_ms` and `trace`.
`metrics.json` gives, per set, accuracy (public only), total and average tokens, average,
p50 and p95 latency, LLM calls and TigerGraph queries per question, trace steps, run time
and cost. The submitted copies of items 2-4, 6 and 7 are kept under `submission/round-2/`
(`out/` is git-ignored). For a real `cost_usd_total`, set `R2_LLM_INPUT_USD_PER_M` and
`R2_LLM_OUTPUT_USD_PER_M` before the runs.

## 2. Pre-submission checklist

Tick each only when done and verified.

**Environment**
- [ ] TigerGraph workspace running and LLM credentials available; `.env` filled from `.env.example`.
- [ ] Clean install: `python3 -m pip install -r backend/requirements.lock && python3 -m pip install --no-deps -e backend`.
- [ ] `cd backend && ruff check src tests && python3 -m pytest -q -p no:cacheprovider` passes.

**Final runs (same code, same settings, working tree clean and committed)**
- [ ] Start clean: delete `out/r2/tg_query_log.jsonl` and `out/r2/metrics.json` (the log is append-only) and run with `FRESH=1`.
- [ ] `./build.sh docs/round-2/data/corpus.jsonl` from scratch; `out/r2/graph_counts.json` written.
- [ ] `FRESH=1 ./run.sh docs/round-2/data/questions_public.jsonl answers_public.jsonl`.
- [ ] `FRESH=1 ./run.sh docs/round-2/data/questions_hidden.jsonl answers_hidden.jsonl` (once).
- [ ] 50 lines in each answers file, no qid missing (a failed question is not written; `r2-run` exits 1 and names it).

**Verification**
- [ ] `python3 scripts/validate_submission.py` (see `--help` for paths) reports no errors: token sums equal, steps numbered, TigerGraph steps have query, params and rows, metrics recompute from the answer files.
- [ ] Every answer has a TigerGraph step (`answers_with_tigergraph_step` is 50 in both blocks); none was produced with `--backend local`.
- [ ] Query-log timestamps fall inside the matching traces (spot-check several qids; the log `ts` is a call's start in UTC).
- [ ] `metrics.json` has both blocks with all fields; hidden `accuracy_pct` is `null`.
- [ ] No question-specific rules in `backend/src/ogr/r2/` (no regex on question wording, no qids, no built-in answers).
- [ ] README matches the code; links and commands checked.
- [ ] Tag `round2-submission` on the committed code, pushed.
- [ ] Package assembled and sent: repo link, the two answer files, `metrics.json`, the query log and the graph counts.

## 3. Live judging

The live-call runbook (start the system, ask a new question, reproduce a submitted hidden
answer and trace) is [LIVE-JUDGING.md](LIVE-JUDGING.md).
