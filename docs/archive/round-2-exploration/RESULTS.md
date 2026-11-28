# Round 2 - Results

Branch `round-2`, 2026-11-23. **No run against TigerGraph or an LLM has been made**
(no credentials). So there is no accuracy, token, latency, cost or query-log
result for the real brief. What exists is offline test results and tool-level
checks, listed below with the command that produces each. Targets are in
[APPLICATION-SPEC.md](APPLICATION-SPEC.md) section 5.

## 1. Measured (offline)

| Check | Result | Command |
|---|---|---|
| Backend test suite | 920 passed (owner-reported; not re-run in full for this document) | `cd backend && python3 -m pytest -q` |
| Round-2 tests only (`tests/r2`) | 227 passed (run 2026-11-23) | `cd backend && python3 -m pytest tests/r2 -q` |
| Tool-level dev checks: `LocalR2Graph` on the real corpus reproduces 32 public gold answers | passes | `cd backend && python3 -m pytest tests/r2/test_dev_checks.py -q` |
| GSQL static checks (query files and install list) | passes | `tests/r2/test_gsql_static.py` |

**What the dev checks mean.** The tools return the rows that contain the gold
answer (for example `medals_by_nation` for Wrestling 2024 gives JPN with 8
golds). They do not show that an LLM picks the right tool, reads the rows
correctly, chooses the right status or cites well. Where the corpus holds more
than the gold lists, the test says what the extra rows are.

**What they do not show.** `LocalR2Graph` is a Python copy of the tools; the
GSQL queries have never run. Parity between the two is unchecked on a server.

## 2. Not measured, and how to measure it

All need credentials in `.env` (TigerGraph and LLM). Run in this order; each
output goes under `out/r2/`.

| Quantity | Command | Output |
|---|---|---|
| Graph counts after loading the corpus (also proves the GSQL installs) | `./build.sh docs/round-2/data/corpus.jsonl` | `out/r2/graph_counts.json` |
| Smoke run, 5 public questions | `cd backend && python3 -m ogr.cli r2-run --questions ../docs/round-2/data/questions_public.jsonl --out /tmp/smoke.jsonl --limit 5` (use a scratch path) | answers with traces; `out/r2/tg_query_log.jsonl` |
| Public answers, self-score, metrics | `./run.sh docs/round-2/data/questions_public.jsonl answers_public.jsonl` | `answers_public.jsonl`, `out/r2/score_public.json`, `out/r2/metrics.json` ("public") |
| Dev and check accuracy | filter `per_question` in `out/r2/score_public.json` by `docs/round-2/data/public_split.json` and average (no CLI flag exists for this; a short script is needed) | accuracy per split |
| Hidden answers and metrics | `./run.sh docs/round-2/data/questions_hidden.jsonl answers_hidden.jsonl` | `answers_hidden.jsonl`, "hidden" block of `metrics.json` (accuracy null) |
| Trace validity | `cd backend && python3 -m ogr.cli r2-metrics --set public --answers ../answers_public.jsonl` prints validator errors and warnings to stderr | warnings: no TigerGraph step, step times vs latency |
| Tokens, latency p50/p95, LLM calls, TigerGraph queries per question, cost | in `metrics.json`; cost needs `R2_LLM_INPUT_USD_PER_M` and `R2_LLM_OUTPUT_USD_PER_M` set | |

Notes that affect the measurement:
- `r2-run` skips qids already in the output file. For a clean measurement delete
  the answers file and `out/r2/tg_query_log.jsonl` first (the log is append-only).
- `run.sh` self-scores only when the questions file has gold answers (public).
- The runtime note: the final public and hidden runs must use the same code and
  settings.

## 3. Known limitations

- Nothing about the live system is known: GSQL syntax, query latency, model tool
  calling, token reporting by the provider.
- The scorer (`ogr.r2.score`) approximates "fact by fact with partial credit";
  the organisers' key and method are unknown, so public accuracy is a proxy.
- Source-record weighing is done by the answering LLM from authority and time
  fields (deviation from D4, [INTERVIEW-LOG.md](INTERVIEW-LOG.md)); its quality
  is untested.
- The `check` split is 14 questions; its score will be noisy.

## 4. Inconsistencies noticed between documents and code (2026-11-23)

- [SOLUTION-DESIGN.md](../../round-2/SOLUTION-DESIGN.md) places the GSQL at `graph/schema_r2_answer.gsql`
  and `graph/queries/r2_*.gsql`; the files are under `backend/src/ogr/graph/`.
- SOLUTION-DESIGN section 2 omits `published_text` on `SourceRecord` and `place`,
  `event_key` on `WON`, which the code has.
- SOLUTION-DESIGN names modules `ogr.r2.build` and `ogr.r2.run` as entry points;
  the scripts call `python3 -m ogr.cli r2-build` and `r2-run`.
- The README says an exception on one question gives a `partial` record and the
  run continues; in code that record is not written (a rerun retries it) and
  `r2-run` exits 1.
- The code docstrings call the query log "item 5" and the graph counts "item 6"
  (the numbering of `data/README.md`); PROBLEM-STATEMENT numbers them 6 and 7.
  [SUBMISSION.md](../../round-2/SUBMISSION.md) uses the PROBLEM-STATEMENT numbering.

## 5. Earlier synthetic harness (superseded)

Everything below was produced for the speculative Round 2, whose judged metric
was assumed to be the Agentic-vs-RAG relative gain. It measures the
claim-resolution layer (`reasoning/`, `harness/`) on generated data with an
oracle parse. It is not the Round-2 result, is not comparable to RAG, and is not
on the Round-2 answering path. Kept as history; its test counts are from
2026-10-24.


Branch `round-2`. Every figure here was produced by a command listed below,
from the committed code. **No live pipeline run has been made in Round 2**:
this session has no TigerGraph, LLM or embedding credentials (gate G5:
build offline first). So there is **no Agentic-vs-RAG result yet**, no
tokens-per-question figure and no live Round-1 regression run. Those are
listed in section 3 with the commands that produce them.

### 5.1. Round-1 regression (offline)

| Check | Result |
|---|---|
| Backend tests (`pytest`), including every Round-1 routing, contract, trace and anti-overfitting test | 692 passed (597 at the start of Round 2; the additions are Round-2 and backlog tests) |
| Frontend (`npm run lint`, `tsc -b`, `vitest`) | lint clean (one pre-existing warning), typecheck clean, 63 passed |
| Round-1 routes on a graph **without** the fact layer | unchanged; no Q6 call is made (`test_claims_route.py::test_a_graph_without_the_fact_layer_is_never_asked_for_claims`) |
| Round-1 routes on a graph **with** the fact layer and one firm value | unchanged, `direct_route`, no confidence field (`test_one_firm_value_keeps_the_round1_route`) |
| Temporal detector on all 165 Round-1 questions (public, hidden, paraphrase) | none time-scoped (`test_no_round1_question_is_time_scoped`) |
| Shared answer prompt (CORE-02) | unchanged, byte for byte |
| Live public-100 baseline on `round-2` | **not run** (no credentials) |

### 5.2. Reasoning layer on the injection harness (offline, component level)

**What this measures:** temporal scoping, supersession, conflict resolution
and confidence. The harness metadata supplies the subject and attribute (an
*oracle parse*), and the code under test does the rest. No intent parse,
retrieval, LLM or RAG baseline is involved.

**What this does not measure:** pipeline accuracy. These numbers are not
comparable to RAG and are not the Round-2 result. They show what the claim
tools can contribute once parsing and linking are right, and they are where
the weights were fitted (dev) and checked (test).

Setup: generator v1, seed 2026, 100 questions per subset (300), split by
event into dev 143 / test 157. Weights and Platt scaling were fitted on dev
only by grid search (accuracy first, then raw Brier); every figure below is
on **test**.
- Difficulty sets the number of false sources (1–3), how close the false
  values are, and the chance of a reversal or an unconfirmed rumour in
  evolving items.
- Reliability info is what each record says about its source:
  - `exact`: class and reliability.
  - `class`: class only, so the class prior applies (an assumption).
  - `none`: neither, so sources can be told apart only by agreement across
    the dataset.
- Uncertain items include lone hedged reports that are wrong (`hedge_error`
  0.3), whose truth is stated nowhere. They are unanswerable by design;
  accuracy on answerable items is shown in brackets.

| Difficulty | Reliability info | Conflicting acc. (default → fitted) | Evolving acc. | Uncertain acc. (answerable) | All acc. | All ECE (default → fitted) | All Brier (fitted) |
|---|---|---|---|---|---|---|---|
| 1 | exact | 0.983 → 1.000 | 1.000 | 0.824 (1.000) | 0.943 | 0.297 → 0.034 | 0.045 |
| 1 | class | 0.983 → 1.000 | 1.000 | 0.824 (1.000) | 0.943 | 0.300 → 0.041 | 0.044 |
| 1 | none | 0.966 → 0.983 | 1.000 | 0.824 (1.000) | 0.936 | 0.341 → 0.014 | 0.051 |
| 2 | exact | 0.759 → 0.966 | 1.000 | 0.863 (1.000) | 0.943 | 0.313 → 0.079 | 0.089 |
| 2 | class | 0.759 → 0.966 | 1.000 | 0.863 (1.000) | 0.943 | 0.313 → 0.090 | 0.087 |
| 2 | none | 0.741 → 0.845 | 1.000 | 0.863 (1.000) | 0.898 | 0.385 → 0.063 | 0.103 |
| 3 | exact | 0.466 → 0.948 | 1.000 | 0.863 (1.000) | 0.936 | 0.256 → 0.015 | 0.054 |
| 3 | class | 0.448 → 0.931 | 1.000 | 0.863 (1.000) | 0.930 | 0.273 → 0.013 | 0.057 |
| 3 | none | 0.397 → 0.828 | 1.000 | 0.863 (1.000) | 0.892 | 0.308 → 0.030 | 0.095 |

Reading it:
- **Conflicting** is where the weighing matters. Default weights fall to
  0.40–0.47 at difficulty 3, where several low-reliability sources state the
  same false value. With fitted weights it is 0.93–0.95 when the source
  class is known, and 0.83 when nothing about the sources is known; that is
  the limit of agreement-based estimation against a coordinated majority.
- **Evolving** is 1.00 everywhere, including reversals and unconfirmed
  rumours. With an oracle parse, this harness is easy for the resolver; in
  the pipelines the work is in parsing and linking the question, which this
  table does not exercise. A harder evolving generator is listed in
  section 4.
- **Uncertain**: every answerable item is right. The overall accuracy is
  capped by the unanswerable items, which is intended.
- **Calibration**: fitted Platt scaling brings overall ECE from 0.26–0.39
  down to 0.01–0.09 on test. Per subset it is uneven: uncertain is
  under-confident at difficulty 2 (ECE 0.21–0.26), because one global
  mapping serves all subsets. That is reported, not tuned away.

Reproduce one row (about 30 s, no credentials needed):

```
python -m ogr.cli harness --n 100 --difficulty 2 --reliability-info class --name r2-d2-class --offline
# writes out/harness/r2-d2-class{.jsonl,-questions.jsonl,-dev-/-test-/-dryrun-questions.jsonl,
#        .manifest.json,-offline.md,-weights.json}
```

### 5.3. Not measured yet, and how to measure it

All of these need the `.env` credentials. Each step is gated by cost: the
dry run comes first.

| Step | Command | Produces |
|---|---|---|
| Round-1 baseline on `round-2` (before the fact layer) | `make benchmark` | public-100 EM/F1, tokens: the regression reference |
| Add the fact layer (gate G1, approved) | `python -m ogr.cli round2` | Round-2 types, Q5S/Q6, claims for every loaded dataset |
| Load the harness corpus as its own dataset | Settings → Build with `out/harness/<name>.jsonl` (or `POST /build`) | Documents, chunks and claims of the harness |
| Dry run, 10 questions × 3 pipelines | `OGR_ROUND2_WEIGHTS=out/harness/<name>-weights.json python -m ogr.cli batch out/harness/<name>-dryrun-questions.jsonl --out out/r2-dryrun.jsonl` | cost per question before any full run |
| Harness test split × 3 pipelines | same, with `<name>-test-questions.jsonl` | Agentic vs RAG vs GraphRAG per subset, tokens per question, P3 calibration (`python -m ogr.cli report`) |
| Round-1 regression after the fact layer | `make benchmark` again | must match the baseline within run-to-run variance |

**Fairness, as built.** All three pipelines get the same documents. Each
harness record states its source and publication date in its text, so RAG
sees the same provenance the graph holds. Same `k`, same LLM, same
embedding model, same answer prompt.

### 5.4. Known limitations

- The harness is synthetic: generated statements about real Olympic events
  from fictional sources, with neutral wording (no misconduct is attributed
  to any real person). It is a stand-in until the real Round-2 dataset
  arrives.
- Evolving items are solved by the resolver once the subject is known; a
  harder generator (revisions without explicit cues, conflicting revisions,
  as-of dates on a change's boundary) is still to do.
- With no reliability information and a coordinated false majority,
  conflicting accuracy stops around 0.83.
- Calibration is fitted on about 140 dev questions with one global mapping;
  per-subset calibration varies.
- Claims come from key/value blocks only. A prose-only dataset needs the
  LLM extractor (gate G4, allowed, not built).
- The GSQL for the fact layer, Q5S and Q6 has not been installed on Savanna
  yet; its first install is its first syntax check.
