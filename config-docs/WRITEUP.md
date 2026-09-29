# Write-up: when is the agent worth its tokens?

The submission summary: what was built, how it works, what was measured,
where it falls short, and what comes next. Every number below comes from a
run file in `out/` through `python -m ogr.cli report` (the same scorer the
dashboard uses); nothing is estimated unless it says so.

## What we built

One question, three pipelines over the same TigerGraph graph, the same LLM
and the same answer prompt, so the measured difference is the method:

| Pipeline | What it does | What it removes |
|---|---|---|
| RAG | Q5 vector search over 16,669 chunks, top 10, one generation | the graph |
| GraphRAG | the agent's intent parser, then exactly **one** graph query (Q1–Q4), one generation | the loop |
| Agentic GraphRAG | a LangGraph orchestrator: intent parse, entity linking, a **necessity router**, graph tools, an evidence check, fallbacks, a stop rule | nothing |

The graph (Wikipedia Olympic-event pages): 2,951 documents, 2,187 events,
21 Games, 42 sports, 319 venues, with `AT_GAMES`, `IN_SPORT`, `HELD_AT`,
`PREV_EDITION`/`NEXT_EDITION` edges and per-model embedding vertices. Five
installed GSQL queries do all retrieval (TECHNICAL-SPEC §3).

## How the agent decides

1. **Necessity routing.** A fully-specified lookup goes straight to Q1, and a
   count or superlative straight to Q2/Q3. Neither enters the loop. Only
   under-specified, temporal and multi-hop questions pay for the loop
   (`router.py`). A count of one named event's attribute ("how many nations
   competed in *event*") is a lookup, not a count (`refine_route`).
2. **Exact anchors.** Entity linking resolves sport, Games and venue against
   the graph's own vocabularies, and derives the event's id the way ingest
   builds it, so a lookup finds *that* edition. It does not find the same
   name in another year.
3. **Evidence check, then fallbacks.** After each graph step: a deterministic
   scope check and one LLM groundedness check. On failure the agent falls
   back to Q5 similarity or `HAS_CHUNK` document text, reranked by a
   cross-encoder. Each fallback is recorded as a strategy change.
4. **A stop rule** (sufficient evidence, no further action, step or token
   budget), reported on every answer with the full trace.

Every answer carries its citations and their evidence text, and a
**grounding** score: the share of the answer's names found in the evidence it
cites.

## Results (public set, 100 questions, final system: run `r5-public`)

| Pipeline | EM | F1 | Grounded | Median tokens |
|---|---|---|---|---|
| RAG | 0.59 | 0.65 | 0.93 | 6,453 |
| GraphRAG | 0.63 | 0.63 | 0.41 | 2,522 |
| **Agentic GraphRAG** | **0.98** | **0.99** | 0.79 | **2,550** |

The agent is 39 points more accurate than RAG **and** spends 40% of RAG's
median tokens. It is right on 39 questions RAG gets wrong, and wrong on none
that RAG gets right.

| Type | n | RAG | GraphRAG | Agentic | Agentic − RAG | Agentic ÷ RAG tokens |
|---|---|---|---|---|---|---|
| aggregation | 21 | 0.14 | 1.00 | 1.00 | **+0.86** | 0.30× |
| superlative | 10 | 0.00 | 0.90 | 0.90 | **+0.90** | 0.94× |
| multi_hop | 28 | 0.57 | 0.07 | 0.96 | **+0.39** | 1.02× |
| lookup | 19 | 1.00 | 0.95 | 1.00 | 0.00 | 0.30× |
| temporal | 22 | 0.95 | 0.59 | 1.00 | +0.05 | 1.05× |

- **Multi-hop is where the loop earns its cost.** GraphRAG, the same graph
  without the loop, scores 0.07; the agent scores 0.96 at about RAG's cost.
- **The router is the efficiency story.** 62 of 100 questions take the
  direct route: median 1,924 tokens, EM 1.00. The 38 loop runs cost a median
  of 7,416 (EM 0.95). *Estimate:* sending the direct questions through the
  loop would have spent about 277k more tokens.
- **Answer verification:** 90 of 100 Agentic answers are supported by their
  graph evidence, and 7 were resolved to a page title. The 11 conflict flags
  in this run came from a detector bug (it read infobox keys and years as
  prose figures). That bug was fixed after r5 (`535565a`); the flags are
  annotations only and changed no answer.
- **The two misses.** pub-067: the parse put the venue in the event slot and
  dropped the day. It is fixed after r5 (`61b8927`) and verified live
  (`r6-two`: Rosannagh MacLennan). pub-088: the model answered with a field
  copied from the evidence row ("Men's giant slalom games: 1992 Winter"). That
  answer form is now cut before title resolution, but on the live re-run the
  intent parse routed the question differently. This is the accepted
  intent-parse variance (Limitations).

Progression on the same set and LLM: Agentic EM 0.74 (r1) → 0.80 (r2) → 0.91
(r4) → 0.98 (r5). RAG, the control, stayed at 0.59–0.62 throughout.

## Earlier results (run `r2-public`)

LLM `nvidia/nemotron-3-super-120b-a12b` for all three pipelines;
embeddings `bge-large-en-v1.5`.

| Pipeline | EM | F1 | Grounded | Median tokens | Mean latency |
|---|---|---|---|---|---|
| RAG | 0.62 | 0.67 | 0.92 | 6,404 | 39.5 s |
| GraphRAG | 0.49 | 0.53 | 0.38 | 2,335 | 91.3 s |
| **Agentic GraphRAG** | **0.80** | **0.83** | 0.75 | 4,516 | 127.4 s |

Latency is inflated by provider rate limiting (HTTP 429 retries) during the
run; token counts are provider-reported and unaffected.

**Where the agent pays for itself** (EM by question type; the token column
is the mean of per-question Agentic ÷ RAG ratios, as on the dashboard):

| Type | n | RAG | GraphRAG | Agentic | Agentic − RAG | Agentic ÷ RAG tokens |
|---|---|---|---|---|---|---|
| aggregation | 21 | 0.19 | 0.86 | 0.86 | **+0.67** | 0.33× |
| superlative | 10 | 0.00 | 0.20 | 0.20 | +0.20 | 0.94× |
| multi_hop | 28 | 0.61 | 0.07 | 0.68 (0.75 after the venue fix, `r3-multihop`) | +0.07 (+0.14) | 1.75× |
| lookup | 19 | 1.00 | 0.89 | 1.00 | 0.00 | 0.53× |
| temporal | 22 | 1.00 | 0.45 | 1.00 | 0.00 | 1.16× |

- Agentic was right on **19** questions RAG got wrong, and wrong on **1** that
  RAG got right.
- On counting it is both more accurate and **3× cheaper** than RAG. On
  lookups and temporal questions it ties RAG at about half to 1.2× the
  tokens.
- **The router is the efficiency story.** 56 of 100 questions were answered
  on a direct route: median 1,945 tokens, EM 0.84. The 44 loop questions
  cost a median 11,668 tokens (EM 0.75). *Estimate:* sending the direct
  questions through the loop would have spent about 515k more tokens.
- **The graph without the loop is not enough.** GraphRAG (one query) scores
  0.07 on multi-hop, where the agent scores 0.68–0.75. The loop is what turns
  graph structure into multi-hop answers.

**What changed from the baseline** (`r1-public`, same LLM): Agentic EM
0.74 → 0.80, lookup 0.74 → 1.00, aggregation 0.71 → 0.86. RAG stayed at
0.62, as a control should. Each root cause and its fix, with the owner's
decision where one changed routing or retrieved context, is in
`config-docs/SCORE-AUDIT.md`.

**Hidden set (50 questions, run once, on the system before answer verification and anchor recovery — the `r2` system plus the venue/date fix; kept rather than rerun, by the owner's decision):** 0 pipeline
errors in 150 answers.

| Pipeline | Grounded | Median tokens |
|---|---|---|
| RAG | 0.92 | 6,732 |
| GraphRAG | 0.40 | 3,034 |
| Agentic GraphRAG | 0.64 | 3,129 |

The router answered 36 of the 50 without the loop, at a median of 2,094
tokens; the 14 loop runs cost a median of 12,026. The hidden set has no gold
answers, so there is no EM or F1. The raw outputs (answer, tokens, citations
and every agentic trace) are in `submission/hidden-set-export.json`
(`python -m ogr.cli export`, `make results`).

## Limitations

- **Intent-parse variance.** The same LLM at temperature 0 sometimes parses
  a question into a different operation or anchor slot. Gazetteer recovery
  repairs the anchors (venue, sport, Games, date) from the question's own
  words, but not the operation. We chose not to tune the intent prompt
  against the public set.
- **Ambiguous venue days.** When a venue held several events on the named
  day and the question names no sport, there is no single right answer. The
  agent picks by quoted date text and then by day coverage; it should ask
  back instead.
- **Infobox parsing.** Numbers come from infobox fields, and a few pages
  carry typos (a "competitors: 41000000"). Rows below parse confidence 0.9
  are excluded from counts and reported as excluded.
- **Provider limits.** The free NVIDIA endpoint rate-limits hard. Runs
  resume question by question (`batch` is resumable), but wall-clock
  latency is not representative.
- **Round 2** (conflicting, superseded and uncertain facts): only the first
  step exists. Conflicting infobox and prose figures are reported; facts
  are not versioned.
- **Sessions are in memory,** so the deployment is one API process.

## Next steps

1. Ask back when the evidence names several events that fit the question.
2. A second intent parse when the operation and the linked anchors disagree.
3. Round 2: facts carry source and date; supersession and source authority.
4. A shared session store for several API replicas.

## Demo script (3 minutes)

Slides: the "Agentic GraphRAG — final presentation" deck (13 slides, speaker
notes on each). Before recording, sign in with the **viewer** key so the demo
shows that a viewer can ask and read but not rebuild.

1. **Build screen** (20 s): the graph loads from the corpus. The counts
   match the numbers above, and the embedding model and its index state are
   shown.
2. **Search, a counting question** (40 s): "How many biathlon events at the
   2006 Winter Olympics had more than 72 competitors?" RAG guesses; GraphRAG
   and Agentic answer 4. The Agentic trace shows the direct route (Q2), the
   four events it counted, and each one cited.
3. **Search, a venue question** (60 s): "Who won the gold medal in the event
   held at Beijing National Stadium on 16 August 2008?" Show the trace:
   venue → the 2008 events there → the one on 16 August → Valerie Vili, with
   the strategy change and stop reason. GraphRAG, with no loop, cannot chain
   it.
4. **Dashboard** (40 s): the per-type worth-it table (aggregation "Worth
   it", lookup "Overkill"). Then the direct-vs-loop token split, and
   grounding per pipeline.
5. **Close** (20 s): the agent is not always better. It pays where
   structure matters (counts, chains), costs less where the router skips
   the loop, and ties RAG on single facts.

## Judges' Q&A: likely questions, short answers

- **Is the comparison fair?** One LLM for all three pipelines, a byte-identical
  answer prompt, one deterministic scorer. Every graph-side fix runs in
  GraphRAG too, so Agentic − GraphRAG is the loop and GraphRAG − RAG the graph.
- **Did you tune on the public set?** No prompt was tuned. Each gain is a named
  root cause found in the traces (`SCORE-AUDIT.md` §3–§6), and RAG, which no
  fix touched, stayed at 0.59–0.62 in every run.
- **Why is the agent's grounding lower than RAG's?** RAG cites long text
  chunks, so its answer's names are almost always in them. A count answer
  cites a count row with no prose. The verification step reports graph
  support separately: 90 of 100 agentic answers.
- **When is the agent not worth it?** Single-fact lookups and dates: RAG is
  already exact there. The router keeps those cheap (direct route, one query).
- **Why is it cheaper than RAG?** 62% of questions take the direct route
  (median under 2,000 tokens); RAG always sends ten chunks.
- **What fails?** Two of 100 in r5: an intent parse that put the venue in
  the event slot (fixed after r5) and a copied evidence field in the answer.
  The open cases are intent-parse variance and venue days that several
  events share; the right behaviour there is to ask back.
- **Hidden set?** Run once, raw outputs in `submission/`. No gold, so cost,
  routing and grounding only.
- **How is it secured?** No key in the browser bundle: sign-in exchanges a
  typed key for a server-side session; a viewer key cannot build, upload,
  switch embeddings or start benchmarks (`OGR_ADMIN_KEY`).
- **What is novel?** Necessity routing refined after entity linking, exact
  event ids derived the way ingest builds them, gazetteer anchor recovery, a
  zero-token answer-verification step with conflict reporting, per-model
  HNSW indices, and a grounding score that needs no gold.
