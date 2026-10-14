# Jury presentation — speaker notes (10 min)

Deck: `Agentic-GraphRAG-Application-Walkthrough.pptx` (20 slides).
Timing: 9:20 of content + 0:40 buffer. Clock column = where you should be at the end of the slide.

**One-line thesis:** Agentic GraphRAG is 0.98 exact match vs RAG 0.59, at 40% of RAG's median tokens. It wins where structure matters and is routed cheap where it doesn't.

**If behind schedule:** compress slides 11, 12, 14, 15 and 16 to one line each (saves about 60 s).

---

## Opening (0:00–2:00)

### 1 · Title — 0:30 · clock 0:30
- Question: when is an AI agent worth its tokens?
- Answer is measured, per question type, on 100 public questions.
- **0.98** Agentic EM vs **0.59** RAG · **0.40×** RAG's median tokens · **39 wins / 0 losses** vs RAG.

### 2 · Three pipelines — 0:40 · clock 1:10
- Pipelines:
  - RAG: Q5 vector top-10 over 16,669 chunks. No graph, no loop.
  - GraphRAG: shared intent parser + exactly 1 graph query (Q1–Q4). Graph, no loop.
  - Agentic: intent → link → route → graph tools → evidence check → re-query → verify.
- It's an ablation:
  - GraphRAG − RAG = value of the graph.
  - Agentic − GraphRAG = value of the loop.
- Held constant across all three:
  - LLM `nvidia/nemotron-3-super-120b-a12b`, temp 0.
  - Byte-identical answer prompt and the same deterministic scorer.
  - Same graph, same embeddings (bge-large-en-v1.5, 1024-d).
- Every graph-side fix also went to GraphRAG.

### 3 · Agent flow + graph — 0:50 · clock 2:00
- Six stages:
  - **Intent parse:** LLM tool call → operation, anchors, filters.
  - **Entity linking:** gazetteer over the graph's own vocabularies (21 Games, 42 sports, 319 venues). 0 tokens.
  - **Necessity router:** fully specified lookup/count → direct route (1 query). Anything else → investigation loop.
  - **GSQL tools:** Q1 lookup · Q2 count-where · Q3 argmax · Q4 traversal (HELD_AT, PREV/NEXT_EDITION) · Q5 hybrid vector.
  - **Evidence check:** LLM groundedness. On fail, change strategy (similarity search / document chunks).
  - **Answer + verify:** shared prompt. Answer checked against graph rows (support, page-title resolution, conflict flags).
- Graph:
  - 2,951 documents · 2,187 events · 16,669 chunks · 11,343 relationships.
  - Vertices: Document, OlympicEvent, Games, Sport, Venue, Chunk, plus one Embedding_* type per model.
- Loop limits: max 6 steps, 20k tokens per query.

## Application tour (2:00–6:30)

### 4 · Section divider — 0:05 · clock 2:05
- "Every screen shown is the running app on the live TigerGraph graph."

### 5 · Build — 0:25 · clock 2:30
- One shared ingestion with a readiness line per pipeline:
  - RAG needs chunks + vectors.
  - GraphRAG needs the graph.
  - Agentic needs both.
- Deterministic infobox parsing: 0 LLM tokens to build.
- Dataset tracking: a rebuild replaces only its own data. A fresh install adopts an existing graph from TigerGraph.

### 6 · Count question, direct route — 0:35 · clock 3:05
- Q: biathlon events, 2006 Winter, > 72 competitors.
- All three answer **4**.
- Tokens: RAG **8,532** (10 chunks) · GraphRAG 1,851 · Agentic **1,817** = **0.21×** RAG.
- RAG can only count what it happens to retrieve. Here it was right, at 4.7× the cost.
- Agentic cites each counted event (Q2 returns its members).

### 7 · Count trace — 0:20 · clock 3:25
- 5 steps: intent parse → entity linking (2006-Winter, Biathlon; 0 tokens) → Q2 count-where → answer → verification.
- Stop reason: `direct_route`. Plan deviated: no.
- Each step logs tool, tokens, latency, chunks and citations.

### 8 · Multi-hop question — 0:40 · clock 4:05
- Q: gold medallist, event at Beijing National Stadium on 16 Aug 2008.
- Names a venue and a day, not an event.
- Answers:
  - RAG: **Usain Bolt**. Wrong: same stadium, wrong event.
  - GraphRAG: **"Not in context"**. One query cannot chain venue → day → winner.
  - Agentic: **Valerie Vili** (women's shot put). Correct.
- Agentic cost ≈ RAG (1.00×): correct at no extra cost.

### 9 · Strategy change — 0:35 · clock 4:40
- Step 3: Q4 HELD_AT → Q1. **37 events** at the venue, narrowed to **1** by date.
- Step 4: groundedness fails on the row alone.
- Step 5 (highlighted): **strategy change**, fetches the event page text (HAS_CHUNK).
- Step 7: evidence passes. Step 9: answer verified against graph rows.
- 9 steps, 6,461 tokens. Stop reason `sufficient_evidence`.

### 10 · Dashboard, worth it per type — 0:40 · clock 5:20
- Headline: Agentic EM **0.98** / F1 **0.99** · GraphRAG 0.63 · RAG 0.59 / 0.65.
- Median tokens: Agentic **2,551** · GraphRAG 2,523 · RAG **6,453**.
- Verdict per type:
  - Aggregation: **+0.86** at 0.30× → worth it.
  - Superlative: **+0.90** at 0.94× → worth it.
  - Lookup: 0.00 at 0.30× → overkill, but cheap.
- Routing: 62 direct · 35 sufficient evidence · 3 no further action. 21 runs changed strategy.

### 11 · Matrix + scatter — 0:25 · clock 5:45
- Multi-hop: Agentic **0.96** vs GraphRAG **0.07** vs RAG 0.57. The loop, not the graph alone, is the gain.
- Temporal: Agentic 1.00 vs GraphRAG 0.59.
- Scatter: one point per question. Agentic clusters at F1 1.0 and low tokens.

### 12 · Cost, reliability, agents — 0:25 · clock 6:10
- **0 errors** in 300 answers.
- Grounded score needs no gold, so it also works on the hidden set: RAG 0.93 · Agentic 0.79 (count rows carry no prose).
- Only 3 agents call the LLM:
  - Orchestrator: 277k tokens.
  - Answer generation: 161k.
  - Evidence evaluation: 40k.
- Linking, traversal, aggregation and verification cost 0 tokens.

### 13 · Benchmarks + compare — 0:35 · clock 6:45
- Every run is stored with its full config: model, embeddings, k, chunking, budgets.
- r1 → r5 for Agentic: EM **0.74 → 0.98**, median tokens **4,700 → 2,551 (−46%)**.
- RAG flat at **0.59–0.62** throughout: the control. The gains are not noise.
- Export gives the submission JSON: answers, citations with snippets, full traces.

### 14 · Eval table — 0:15 · clock 7:00
- Per question: gold + all three pipelines (answer, EM, F1, P, R, tokens, latency).
- "Disagree only" filter: **66 of 100** questions. This is where the research question lives.

### 15 · History — 0:10 · clock 7:10
- Audit log of every query, build and benchmark, including failed, partial and refused attempts.

### 16 · Settings — 0:20 · clock 7:30
- LLM provider/model switchable at runtime: NVIDIA NIM, Gemini, Groq. One model serves all three pipelines.
- Embeddings:
  - 5 models; each gets its own vertex type and HNSW index; at most 2 stored at once.
  - A query never searches another model's vectors. An incomplete model is refused.
- Re-embed runs in the background (replace or parallel) and resumes after failure.

## Results and close (7:30–9:20)

### 17 · Results — 0:35 · clock 8:05
- EM per type (RAG / GraphRAG / Agentic):

  | Type | RAG | GraphRAG | Agentic |
  |---|---|---|---|
  | Lookup | 1.00 | 0.95 | 1.00 |
  | Multi-hop | 0.57 | 0.07 | **0.96** |
  | Temporal | 0.95 | 0.59 | 1.00 |
  | Aggregation | 0.14 | 1.00 | 1.00 |
  | Superlative | 0.00 | 0.90 | 0.90 |

- Direct route: 62 questions · median 1,924 tokens · EM **1.00**.
- Loop: 38 questions · median 7,416 tokens · EM 0.95.
- Routing saved ≈ **277k** tokens vs sending everything through the loop (estimate).

### 18 · Engineering — 0:30 · clock 8:35
- **Reproducible:** `make reproduce` (build → public + hidden runs → report → export). Run config in every file.
- **Reliable:**
  - Resumable batches.
  - Graph/LLM transients are retried and recorded, never silently degraded.
  - A fresh install adopts an existing graph.
- **Not overfitted:** no question templates and no question-type read in the answer path (enforced by tests). No prompt tuned on the benchmark.
- **Tested:** ~600 backend + 59 frontend tests; UI checked in a real browser.

### 19 · Limits / next — 0:25 · clock 9:00
- Limits:
  - Intent-parse variance at temp 0 (the one open public miss).
  - Shared venue days with no sport named are ambiguous.
  - Round 2 has only its first step: infobox-vs-prose conflict flags.
  - The app is open (no auth).
- Next:
  - Ask back on ambiguity.
  - Second intent parse when operation and anchors disagree.
  - Versioned facts with source authority.
  - Auth at a proxy.

### 20 · Close — 0:20 · clock 9:20
- The agent is not always better. It pays where structure matters: counts, superlatives, multi-hop.
- And it costs less overall: **0.98 EM at 40% of RAG's tokens**.
- Invite questions.

---

## Q&A sheet

| Likely question | Answer |
|---|---|
| Is the comparison fair? | Same LLM, temp 0, byte-identical answer prompt, same scorer, same graph and embeddings. GraphRAG gets every graph fix. Only the method differs. |
| Did you tune on the public set? | No prompt tuned. Each gain fixed a named root cause found in traces. RAG (untouched) stayed 0.59–0.62 across r1–r5. Tests block templates and question-type reads. |
| Why is Agentic grounding (0.79) below RAG (0.93)? | Grounding = answer names found in the cited text. Count answers cite count rows with no prose. Separate graph-support check: 90/100 answers supported. |
| Why is GraphRAG worse than RAG on temporal/multi-hop? | One query, no loop: cannot chain hops or recover from a weak first query. That gap is the loop's value. |
| Why is the agent cheaper than RAG? | 62% of questions take the direct route (median 1,924 tokens). RAG always sends 10 chunks (~6.5k tokens). |
| When is the agent not worth it? | Single-fact lookups and dates: RAG is already exact. The router keeps those cheap (0.30× tokens). |
| What did the agent get wrong? | 2/100 in r5. pub-067: venue parsed into the event slot (fixed after r5, verified live). pub-088: model copied an evidence field (answer now cleaned; residual is intent-parse variance). |
| Hidden set? | 50 questions, run once, 0 errors in 150 answers. Raw outputs and traces in `submission/`. No gold, so cost/routing/grounding only. Produced by the pre-final-round system (decision recorded). |
| How do you handle LLM/graph failures? | Retries with backoff. Failures recorded on the trace step and as errors; a resumed batch re-runs only failed questions. Never turned into "no evidence". |
| Why TigerGraph? | Typed multi-hop traversal (venue → event → edition) plus native vector search (HNSW) in one store. Installed GSQL queries Q1–Q5 keep tool calls deterministic and 0-token. |
| How does it scale to new data? | Upload any JSONL corpus. Datasets are tracked per id, rebuilt independently. Embedding models switch per graph. |
| Round 2 readiness? | First step done: answer verification flags infobox-vs-prose figure conflicts. Next: versioned facts, supersession, source authority. |

## Numbers to have ready

| Item | Value |
|---|---|
| Public set | 100 q · 19 lookup · 28 multi-hop · 22 temporal · 21 aggregation · 10 superlative |
| EM / F1 | Agentic 0.98 / 0.99 · GraphRAG 0.63 / 0.63 · RAG 0.59 / 0.65 |
| Median tokens | Agentic 2,551 · GraphRAG 2,523 · RAG 6,453 |
| Wins / losses vs RAG | 39 / 0 |
| Routing | 62 direct (EM 1.00, median 1,924) · 38 loop (EM 0.95, median 7,416) |
| Progression (Agentic EM) | r1 0.74 → r2 0.80 → r4 0.91 → r5 0.98 |
| Graph | 2,951 docs · 2,187 events · 16,669 chunks · 11,343 relationships |
| Config | k = 10 · chunk 300 / overlap 50 · max 6 steps · 20k tokens per query · LLM max 4,096 output |
