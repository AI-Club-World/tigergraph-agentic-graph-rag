# Score audit against the hackathon rubric

Status: **Phase 1 baseline.** Kept out of git until the owner decides
(an earlier instruction was not to commit scores).

## 1. Rubric as the guidebook defines it

The guidebook's "How You'll Be Judged" table is the source. It gives weights
but no per-criterion scale, so each criterion is scored here on 0–10
(target ≥ 9).

| # | Criterion (guidebook wording) | Weight | What the judges look for |
|---|---|---|---|
| C1 | Investigation accuracy | 30% | Answers complex questions correctly and completely using the right evidence |
| C2 | Evidence quality & explainability | 15% | Grounded answers, clear citations, a clear investigation path |
| C3 | Agentic effectiveness & efficiency | 15% | Right retrieval methods, agentic steps where they add value, accuracy balanced with token cost |
| C4 | Agentic design, engineering & code quality | 15% | Architecture, tool use, reliability, reproducibility, repo quality |
| C5 | Innovation | 15% | Novel investigation methods, graph reasoning, or UX |
| C6 | Final presentation & Q&A | 10% | Demo quality, technical clarity, answers to judges |

The guidebook also lists required deliverables: a working system, the repo,
an architecture diagram, a demo video, a metrics dashboard (tokens,
accuracy, completeness), and raw outputs for all 50 hidden questions
(answers, tokens, agentic trace).

**How this differs from the brief:**
- "Relative accuracy improvement (Agentic vs RAG)" is not a criterion. C1
  judges absolute correctness and completeness. The agentic-vs-RAG gap and
  its token cost are judged under C3, and the guidebook's objective ("are
  the extra steps worth the cost?").
- The brief's architecture and agent-design items are one criterion (C4).
- Token efficiency is part of C3.
- C5 (Innovation) and C6 (Presentation) were missing from the brief.

## 2. Baseline

No eval-score tool exists in the repo; `backend/src/ogr/eval/scorer.py`
grades answers from a benchmark run. No benchmark run exists: the dashboard
data in `frontend/src/fixtures/` is synthetic, and this container has no
TigerGraph or LLM credentials. So every score below is **rubric-based**
(argued from the rubric against the code and deliverables, as in the
2026-09-27 review). None is measured.

| Criterion | Current | Target | Gap | Basis |
|---|---|---|---|---|
| C6 Presentation | 4.0 | 9 | **5.0** | No demo video, write-up or real results in the repo |
| C1 Accuracy | 5.0 | 9 | **4.0** | Never measured; pipelines and scorer are sound but unproven |
| C3 Effectiveness | 6.5 | 9 | 2.5 | Cost-aware routing exists; no measured evidence it pays off |
| C5 Innovation | 6.5 | 9 | 2.5 | Necessity router, per-type "worth it" view, per-model indices; not showcased |
| C2 Evidence | 7.5 | 9 | 1.5 | Citations match context and the trace is full; no grounding metric |
| C4 Engineering | 7.5 | 9 | 1.5 | 578 tests, CI guards, reproduce target; GSQL untested live, key exposure |
| **Weighted** | **6.1** | | | |

## 3. Root causes and fixes (largest gap first)

Legend: **S** = safe to implement directly; **R** = requires rethinking a
settled decision (asked before implementing); **U** = needs the user
(credentials, recording a video).

### C6 Presentation (gap 5.0)
- **No demo video.** Deliverable; only a person can record it (U). An
  agent can script it (S).
- **No write-up** (what was built, how it works, key results, limitations,
  what next). S: `config-docs/WRITEUP.md`, with results filled from a real run.
- **No real numbers to present.** Blocked on the C1 run (U).
- **The diagram is mermaid source only.** S: render it into README.

### C1 Investigation accuracy (gap 4.0)
- **Root cause: no measured run.** Accuracy cannot be judged, or improved
  with evidence, until `make reproduce` runs. That needs a TigerGraph
  workspace and an LLM key in the environment (U).
- **Fixes to accuracy code are deferred until there is a run** that shows
  which question types fail. Changing routing, chunking, k or prompts
  without one would be guessing, and would risk the other criteria (R once
  identified).
- Already done: the scorer no longer marks correct answers wrong (lists,
  dashes, numbers); the prompt asks for full titles
  (`common/contracts.py`, `common/names.py`).

### C3 Agentic effectiveness & efficiency (gap 2.5)
- **No per-question-type evidence of when the agent pays for itself.** The
  dashboard computes it (`frontend/src/Dashboard.tsx`), but nothing exports
  it for the submission. S: `ogr.cli report <run>` writes a markdown
  report: per type, the agentic−RAG EM/F1 gap, the token ratio and a
  verdict; tokens saved by direct routes; stop-reason and tool mix.
- **Hidden-set submission bundle.** Records hold answers, tokens and trace,
  but there is no export in the organisers' shape. S: `ogr.cli export`.

### C5 Innovation (gap 2.5)
- **Novel parts exist but are not showcased** (necessity routing that
  skips the loop, evidence-driven tool choice, per-type worth-it verdicts,
  per-model HNSW switching). S: a write-up section, and a "router savings"
  counterfactual in the report (tokens a forced loop would have spent,
  estimated from measured loop runs of the same type).
- **Round 2 (conflicting, superseded and uncertain facts) is not
  implemented** (`backend/src/ogr/pipelines/p3_agentic/` has no
  conflict/supersession logic). New scope with deadline risk (R).

### C2 Evidence quality & explainability (gap 1.5)
- **No grounding metric.** Scores are EM/F1 and retrieval P/R/completeness
  (`eval/scorer.py`); nothing checks that an answer is supported by the
  evidence it cites. S: a deterministic `grounded` score (the normalized
  answer's names occur in the cited evidence text), stored and shown for
  all three pipelines. No LLM, no change to answers.
- **The investigation path is shown per question** (`TracePanel.tsx`) but
  not summarised per run. Covered by the C3 report.

### C4 Engineering (gap 1.5)
- **Graph query errors are silent.** `graph/client.py` `_run_query` and
  `hybrid_search` return `[]` on any error, so an outage reads as "no
  evidence". S: record the error on the trace step and in the record's
  error detail. Answers and status logic are unchanged.
- **GSQL never run against a live TigerGraph.** S: `make smoke`, a
  one-question live smoke test; running it needs U.
- **The browser API key is not a secret**, so anyone holding it can reset the
  graph or spend quota (`frontend/src/config.ts`, `api/security.py`). R: a
  server-side admin key for destructive routes changes the auth design.
- **No container image.** S: Dockerfile for the backend (reproducibility).

## 4. Interview log

(Filled in as each R item is raised and decided.)

## 5. Implementation plan

(Ordered once the Phase 3 decisions are in.)

## 6. Post-implementation scores

(Appended after re-scoring.)
