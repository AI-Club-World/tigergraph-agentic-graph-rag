# Score audit against the hackathon rubric

Status: **Phase 4 in progress.** Safe fixes are implemented; the measured
baseline run is waiting on the graph rebuild (§5). Committed at the owner's
request (§4).

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

| # | Question | Decision |
|---|---|---|
| 1 | Which rubric? | The guidebook's six criteria and weights (§1), not the brief's list |
| 2 | Deadline? | Round 1, Sep 30 IST. Round 2 conflict reasoning (C5 R item) is out of scope |
| 3 | Commit this audit? | Yes. This overrides the earlier "do not commit the score" instruction for this file |
| 4 | Live run for C1? | Yes. The owner provided TigerGraph and LLM credentials; they live only in the git-ignored `.env` and should be rotated |
| 5 | TigerGraph workspace stopped (no auto-start) | The owner started it |
| 6 | Reset the graph (old one-vector-per-chunk layout)? | Yes, reset and rebuild |
| 7 | Which LLM for all three pipelines? | NVIDIA `deepseek-v4.1-flash` (one model for P1, P2 and P3) |
| 8 | Embeddings (Cloudflare quota spent, HTTP 429) | The owner's self-hosted `bge-large-en-v1.5` service (`EMBEDDING_HOST_URL`), checked equal to local bge-large (cosine 1.000) |
| — | Accuracy fixes (routing, chunking, k, prompts) | Not decided yet. Raised only once the measured run shows which question types fail (§3 C1) |
| — | Server-side admin key for destructive routes (C4 R item) | Not raised: it changes the auth design. The documented security model (README) stands |

## 5. Implementation plan

Largest gap first. Done items name their commit on `application-integration`.

| # | Criterion | Item | Class | State |
|---|---|---|---|---|
| 1 | C1/C4 | Reranker falls back to the same model locally when Cloudflare fails or is not configured | S | Done, 7930097 |
| 2 | C1/C4 | Embedding tiers: self-hosted host → Cloudflare → local; `EMBEDDING_CLOUDFLARE` / `EMBEDDING_REMOTE` switches | S | Done, 7930097, 02b37a9 |
| 3 | C2 | Deterministic `grounded` score from citation snippets, all three pipelines; stored scores never trusted | S | Done, 02b37a9 |
| 4 | C3/C5 | `ogr.cli report`: per-type Agentic − RAG gap, token ratio, verdict, router savings estimate | S | Done, ca51629 |
| 5 | C6/deliverable | `ogr.cli export`: hidden-set raw outputs (answer, tokens, trace) | S | Done, ca51629 |
| 6 | C2 | Grounded column on the dashboard (works without gold) | S | Done, e345f25 |
| 7 | C4 | Graph query failures reported in trace notes and `error_detail` | S | Done, 38b4e54 |
| 8 | C4 | `make smoke`, `make results`; docs for all of the above | S | Done, f47c073 |
| 9 | C1 | Rebuild the graph (per-model layout), run public 100 + hidden 50 with one LLM | U | Running: rebuild in progress |
| 10 | C1 | Root-cause failing question types from the run; accuracy fixes | R | After 9, each raised with the owner first |
| 11 | C6 | `WRITEUP.md` with measured results; demo video script | S | After 9 (needs real numbers) |
| 12 | C6 | Record the demo video | U | Owner |

**Blocker on 9 (2026-09-27):** the self-hosted embedding service's Cloudflare
quick tunnel went down during the build (every request returns a Cloudflare
Tunnel error page, HTTP 500). The build fell back to local bge-large on CPU,
which gives the same vectors at about 1.2 chunks/s, roughly 4 hours for
16,669 chunks. A restarted host (a new tunnel URL in `EMBEDDING_HOST_URL`)
would bring that back to minutes.

## 6. Post-implementation scores

(Appended after re-scoring.)
