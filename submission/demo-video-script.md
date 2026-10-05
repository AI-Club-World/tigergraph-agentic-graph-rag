# Demo video script — Agentic GraphRAG (about 4 minutes, intro to outro)

**Bold lines** are what you do on screen. Quoted lines are what you say.
The two Search questions take 10–20 seconds each to answer: the lines marked
*(while it runs)* are written to fill that wait, so nothing is lost to silence.

## Before you record

- Backend and frontend running; the three status lights in the header green.
- Full-screen browser, zoom 100%, dark theme, other tabs closed.
- Open the Dashboard once with `?run=r5-public` so it loads instantly.
- Run both Search questions once beforehand to warm up the LLM.
- Have the two questions ready to paste.
- Open the deck on slide 1 (title) for the intro and slide 20 (close) for the
  outro, or record those two parts on camera. Fill in your names first.

---

## Intro — title slide (0:00–0:20)

**Show slide 1 of the deck (or yourself on camera).**

> Hello, I'm [your name] from team [team name], and this is our entry for the
> TigerGraph Agentic GraphRAG hackathon. AI agents can answer harder
> questions, but they spend more tokens doing it. So we built an application
> that measures, question by question, when an agent is actually worth its
> cost. In the next four minutes I'll show you the application live, the
> results, and why you can trust them.

## 1. The fair test — Search page, empty (0:20–0:35)

**Switch to the app's Search page. Point at the three pipeline columns.**

> Every question runs through three pipelines side by side: RAG, which is
> vector search only; GraphRAG, which makes one graph query; and our agent,
> which can plan and re-query. All three share the same LLM, prompt, graph and
> scorer, so only the method differs.

## 2. The graph — Build page (0:35–0:55)

**Click Build. Point at the three readiness columns, then the counts at the bottom.**

> The Build page loads Olympics Wikipedia articles into one TigerGraph graph:
> 2,951 documents, 2,187 events linked to their Games, sport and venue, 11,343
> relationships and 16,669 chunks with vector embeddings. Building uses no
> LLM, so it costs zero tokens.

## 3. A counting question — direct route (0:55–1:35)

**Click Search. Paste and click Compare:**
`How many biathlon events at the 2006 Winter Olympics had more than 72 competitors?`

> *(while it runs)* Here's how the agent decides. It parses the question into
> an operation and filters, then links "2006 Winter" and "Biathlon" to the
> graph's own vocabulary, at zero tokens. A router then asks: is one graph
> query enough? For a fully specified count it is, so it skips the loop and
> runs one installed GSQL query.

**When done: point at the verdict strip, then the Agentic column, then scroll to the trace.**

> All three answer 4. But RAG read ten chunks and spent 8,532 tokens. The
> agent spent 1,817, a fifth of that, and cites the four events it counted.
> The trace shows every step with its tool, tokens and time, and the stop
> reason: direct route.

## 4. A multi-hop question — the loop (1:35–2:25)

**Paste and click Compare:**
`Who won the gold medal in the event held at Beijing National Stadium on 16 August 2008?`

> *(while it runs)* This one names a stadium and a day, not an event, so
> it needs several hops: venue, then events, then date, then winner. That
> sends the agent into its investigation loop.

**When done: point at each column's answer.**

> RAG answers Usain Bolt: right stadium, wrong event. GraphRAG makes one query
> and can't chain the hops. The agent answers Valerie Vili, women's shot put,
> which is correct.

**Scroll to the trace; point at the orange step, then the last step.**

> In the trace, the agent found 37 events at the stadium and narrowed them to
> one by date. Its evidence check failed, so it changed strategy and read the
> event's page before answering, then verified the answer against the graph.

## 5. Results — Dashboard (2:25–3:00)

**Click Dashboard. Point at the headline table.**

> Over 100 public questions, the agent scores 0.98 exact match against 0.59
> for RAG and 0.63 for GraphRAG. Its median cost is 2,551 tokens against
> 6,453 for RAG, so it's more accurate and cheaper. It got 39 questions right
> that RAG got wrong, and lost none.

**Point at the "Is the agent worth it" table, then scroll to the stop reasons.**

> Counting and superlatives gain around 0.9; multi-hop reaches 0.96 against
> 0.07 for GraphRAG, so the loop makes the difference. On simple lookups the
> agent is overkill, so 62 questions take the direct route, all correct.

## 6. Why you can trust it — Run benchmark and Eval table (3:00–3:25)

**Click Run benchmark. Tick r1-public and r5-public; scroll to the comparison.**

> Every run is stored with its configuration. From our first run to our last,
> the agent went from 0.74 to 0.98 with 46 percent fewer tokens. Each gain
> fixed a root cause found in the traces, not a tuned prompt; RAG, which no
> fix touched, stayed flat.

**Click Eval table; tick "Pipelines disagree only".**

> The Eval table puts every answer side by side; filter to where the
> pipelines disagree.

## 7. Engineering — History and Settings (3:25–3:40)

**Click History, then the gear icon; scroll to the embedding models.**

> History logs every query, build and benchmark, failures included. In
> Settings you can switch the LLM or the embedding model; each model has its
> own vector index, so searches never mix models.

## Outro — closing slide (3:40–4:00)

**Switch to slide 20 of the deck (or back to camera).**

> To sum up: the agent isn't always better, but it pays where structure
> matters. It's exact on counts, 0.96 on multi-hop questions, and overall
> it uses 40 percent of RAG's tokens. The code, results and full traces are
> in our repository. Thank you for watching, and we'd be happy to take
> your questions.

---

**Length:** about 580 spoken words, intro and outro included. Read at a
natural pace, with the fill-ins spoken while answers load, it runs about
4 minutes. If you run long, drop section 7 (History and Settings).

## What this script covers

| Judging point | Where it is said |
|---|---|
| What we built and why (problem, hackathon, what the video shows) | Intro |
| Fair comparison (same LLM, prompt, graph, scorer) | 1 |
| TigerGraph graph design and scale | 2 |
| Agent design: intent parse, zero-token linking, necessity router, GSQL tools | 3 |
| Token efficiency on a single question (1,817 vs 8,532) | 3 |
| Multi-hop reasoning, strategy change, answer verification, citations | 4 |
| Measured accuracy and cost (0.98 vs 0.59; 2,551 vs 6,453 tokens; 39 wins, 0 losses) | 5 |
| Where the agent is and isn't worth it; the loop's value (0.96 vs 0.07) | 5 |
| No benchmark tuning: root-cause fixes, RAG as a flat control, anti-template tests | 6 |
| Reproducibility, audit log, per-model vector indexes | 6, 7 |
| Takeaways, where to find the work, thanks | Outro |

**If an answer differs on the day** (the LLM can vary between runs): describe
what is on screen, for example "RAG picks a different event". The point to
make is that only the agent chains stadium, day and winner.
