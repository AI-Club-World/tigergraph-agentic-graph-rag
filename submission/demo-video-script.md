# Demo video script — Agentic GraphRAG (about 3 min 45 s)

Speak at a steady pace (about 140 words a minute). **Bold lines** are what
you do on screen; the rest is what you say. Times are cumulative.

## Before you record

- Backend and frontend running, all three status lights in the header green.
- Browser at full screen, zoom 100%, dark theme. Close other tabs.
- Open the Dashboard once with `?run=r5-public` so it loads instantly later.
- Run both Search questions once beforehand (warms the LLM; the second run is
  faster). Answers come back in about 10–20 seconds: keep talking while they run.
- Copy the two questions somewhere you can paste them from.

---

## 1. Opening — Search page, empty (0:00–0:20)

**Show the Search page. Point at the three pipeline columns.**

> Hi, this is our Agentic GraphRAG application on TigerGraph. It answers one
> question: when is an AI agent worth its tokens? Every question runs through
> three pipelines at once: plain RAG, GraphRAG with one graph query, and our
> agent. Same LLM, same prompt, same graph — only the method changes.

## 2. Build page (0:20–0:45)

**Click Build. Point at the three columns, then the counts at the bottom.**

> The Build page loads the Olympics Wikipedia corpus into one shared
> TigerGraph graph: about three thousand documents, two thousand Olympic
> events, sixteen thousand chunks with embeddings and eleven thousand
> relationships. Each column shows when that pipeline can answer. Building
> uses only the embedding model, never an LLM, so it costs no tokens.

## 3. Search — a counting question (0:45–1:25)

**Click Search. Paste and click Compare:**
`How many biathlon events at the 2006 Winter Olympics had more than 72 competitors?`

> First, a counting question. *(while it runs)* RAG has to find the right
> chunks and count them itself. Our agent parses the question, links "2006
> Winter" and "Biathlon" to the graph for free, and its router sees a fully
> specified count, so it takes the direct route: one graph query.

**When done: point at the verdict strip, then the Agentic column, then scroll to the trace.**

> All three say four. But look at the cost: the agent used about a fifth of
> RAG's tokens. The trace below shows every step — five steps, the tool each
> one called, its tokens and time — and why it stopped: direct route.

## 4. Search — a multi-hop question (1:25–2:10)

**Paste and click Compare:**
`Who won the gold medal in the event held at Beijing National Stadium on 16 August 2008?`

> Now a harder one. The question names a stadium and a day, not an event.
> *(while it runs)* The agent has to find every event held at that stadium,
> narrow them to that day, then find the winner.

**When done: point at each column's answer, then scroll to the orange step in the trace.**

> RAG picks a plausible but wrong event. GraphRAG, with only one query, can't
> chain the hops. The agent answers Valerie Vili, women's shot put — correct.
> And here, highlighted, the agent judged its evidence too weak and changed
> strategy, reading the event page before answering. Every answer is
> verified against the graph and cites its sources.

## 5. Dashboard (2:10–2:45)

**Click Dashboard. Point at the headline table, then the per-type table.**

> The Dashboard shows our final run over the 100 public questions. The agent
> scores 0.98 exact match against 0.59 for RAG, using 40 percent of RAG's
> tokens. This table answers our question per type: the agent is worth it on
> counting, superlatives and multi-hop, and overkill on simple lookups — so
> the router keeps those cheap.

**Scroll slowly past the matrix, the cost table and the agents table.**

> Below: every metric per type, cost and latency, zero errors, and which
> agents ran — most of them are graph calls that cost no tokens.

## 6. Run benchmark and Eval table (2:45–3:15)

**Click the Run benchmark tab. Tick r1-public and r5-public; scroll to the comparison.**

> Every benchmark run is kept with its model and settings, and you can start
> new ones from here. Comparing our first and final runs: the agent went from
> 0.74 to 0.98, while using 46 percent fewer tokens. RAG never moved — proof
> the gains are real, not tuning.

**Click the Eval table tab. Tick "Pipelines disagree only".**

> The Eval table shows every question with all three answers side by side —
> filter to where the pipelines disagree.

## 7. History and Settings (3:15–3:40)

**Click History.**

> History logs every query, build and benchmark — including failures — so
> nothing is hidden.

**Click the gear icon; scroll to the embedding models.**

> In Settings you can switch the LLM or the embedding model. Each embedding
> model has its own vector index in TigerGraph, so a query never mixes models.

**Close Settings.**

## 8. Close (3:40–3:55)

**Go back to the Search page with the multi-hop answer on screen.**

> So: the agent isn't always better. It pays where structure matters —
> counting, superlatives and multi-hop — and costs less than RAG everywhere
> else. Thank you.

---

**Word count:** about 560 spoken words, roughly 3 min 45 s at a natural pace.

**If an answer differs on the day** (the LLM can vary): describe what is on
screen, for example "RAG picks a different event" — the point is that only
the agent chains venue, day and winner.
