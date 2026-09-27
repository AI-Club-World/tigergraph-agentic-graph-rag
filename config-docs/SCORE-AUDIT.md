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
| 8 | Embeddings (Cloudflare quota spent, HTTP 429) | The owner's self-hosted `bge-large-en-v1.5` service (`EMBEDDING_HOST_URL`), checked equal to local bge-large (cosine 1.000). Its first tunnel died mid-build; the owner restarted it on a new URL |
| 9 | deepseek-v4.1-flash measured at ~290 s per call (≈50 h for the benchmark) | Switch all three pipelines to NVIDIA `nvidia/nemotron-3-super-120b-a12b` (0.8 s short call, ~2 min per question across three pipelines). Same model for P1, P2, P3 |
| 10 | Q2 returns only a count, so count answers cite nothing (grounding 0) — R item, changes retrieved context | Approved before the run: Q2 also returns the counted events (event_id, name, doc_id); count unchanged |
| 11 | r1: graph rows carry `event_name` but gold answers are page titles (7/10 superlatives named the right event without its title) | Add the Document `title` to Q1–Q4 rows |
| 12 | Hidden set is run once; fixes were still landing | Hold the hidden run until the fixes are in; rerun the public set (`r2`) to measure them first |
| 13 | r1: a COUNT of one named event's attribute ("how many nations competed in <event>") was answered by counting events | Routing rule `refine_route`: such a COUNT becomes a Q1 lookup, in P2 and P3 alike |
| — | Other accuracy fixes (chunking, k, prompts) | None proposed: the r1 failures traced to retrieval and routing, not to those |
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
| 9 | C1 | Rebuild the graph (per-model layout), run public 100 + hidden 50 with one LLM | U | Rebuild done (2,951 docs, 16,669 chunks, index ready); benchmark `r1` running |
| 9a | C2/C1 | Q2 returns its counted events, so count answers are cited | R, approved | Done, e189298 (Q2 reinstalled live) |
| 10 | C1 | Root-cause failing question types from the run; accuracy fixes | R | Done from r1 (below); `r2` measures them |
| 10a | C1 | Graph rows carry the page title (Q1–Q4) | R, approved (11) | Done, 805aa81 |
| 10b | C1 | Q2's count says what it counted; members show the filtered values (repairs 9a: pub-093 answered "unknown") | S (fix to 9a) | Done, 34e3598 |
| 10c | C1 | Q1 finds the named event exactly (derived event_id; page title → the event it describes) | S (lookup bug) | Done, b62d246 |
| 10d | C1 | COUNT of one named event's attribute → Q1 lookup | R, approved (13) | Done, cf0b80e |
| 11 | C6 | `WRITEUP.md` with measured results; demo video script | S | After 9 (needs real numbers) |
| 12 | C6 | Record the demo video | U | Owner |

**Resolved blockers on 9 (2026-09-27):** the first embedding tunnel died
mid-build (the CPU fallback would have taken ~4 h); the owner restarted it
and the rebuild finished in minutes. The LLM was switched (decision 9).

### Baseline measured (r1, 100 public questions, 2026-09-27)

Same LLM for all three pipelines (`nvidia/nemotron-3-super-120b-a12b`), bge-large-en-v1.5.

| Pipeline | EM | F1 | Completeness | Grounded | Median tokens |
|---|---|---|---|---|---|
| RAG | 0.62 | 0.67 | 0.74 | 0.92 | 6,433 |
| GraphRAG | 0.37 | 0.40 | 0.28 | 0.29 | 2,616 |
| Agentic GraphRAG | 0.74 | 0.78 | 0.70 | 0.72 | 4,700 |

Per type, Agentic − RAG EM: aggregation +0.52, multi_hop +0.25, temporal
−0.05, lookup −0.26, superlative 0.00 (all three pipelines 0/10). Agentic
won 20 questions RAG lost; RAG won 8 Agentic lost. Root causes of the 8
losses and the superlatives: page titles missing from graph rows (10a),
Q2 context (10b), wrong-edition / Document-only lookups (10c), COUNT
misrouting (10d); pub-048 and pub-060 (a temporal and a multi-hop miss)
remain open.

## 6. Post-implementation scores

(Appended after re-scoring.)
