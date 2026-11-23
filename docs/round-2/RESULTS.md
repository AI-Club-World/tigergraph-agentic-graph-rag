# Round 2 — Results so far

Branch `round-2`. Every figure here was produced by a command listed below,
from the committed code. **No live pipeline run has been made in Round 2**:
this session has no TigerGraph, LLM or embedding credentials (gate G5:
build offline first). So there is **no Agentic-vs-RAG result yet**, no
tokens-per-question figure and no live Round-1 regression run. Those are
listed in section 3 with the commands that produce them.

## 1. Round-1 regression (offline)

| Check | Result |
|---|---|
| Backend tests (`pytest`), including every Round-1 routing, contract, trace and anti-overfitting test | 692 passed (597 at the start of Round 2; the additions are Round-2 and backlog tests) |
| Frontend (`npm run lint`, `tsc -b`, `vitest`) | lint clean (one pre-existing warning), typecheck clean, 63 passed |
| Round-1 routes on a graph **without** the fact layer | unchanged; no Q6 call is made (`test_claims_route.py::test_a_graph_without_the_fact_layer_is_never_asked_for_claims`) |
| Round-1 routes on a graph **with** the fact layer and one firm value | unchanged, `direct_route`, no confidence field (`test_one_firm_value_keeps_the_round1_route`) |
| Temporal detector on all 165 Round-1 questions (public, hidden, paraphrase) | none time-scoped (`test_no_round1_question_is_time_scoped`) |
| Shared answer prompt (CORE-02) | unchanged, byte for byte |
| Live public-100 baseline on `round-2` | **not run** (no credentials) |

## 2. Reasoning layer on the injection harness (offline, component level)

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

## 3. Not measured yet, and how to measure it

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

## 4. Known limitations

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
