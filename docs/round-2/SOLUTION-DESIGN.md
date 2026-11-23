# Round 2 — Solution design (build contract)

The binding contract for the Round-2 submission. Owner decisions D1–D7 of
[BRIEF-ANALYSIS.md](BRIEF-ANALYSIS.md) §6 are accepted as recommended
(2026-11-23). The brief and data: [PROBLEM-STATEMENT.md](PROBLEM-STATEMENT.md),
[data/README.md](data/README.md).

## 1. Shape

```
./build.sh corpus.jsonl            → ogr.r2.build   : parse → TigerGraph (reset + load), graph counts
./run.sh questions.jsonl answers   → ogr.r2.run     : per question, agent loop → answers.jsonl
                                                      + out/r2/tg_query_log.jsonl, metrics, scoring (public)
```

- New package `backend/src/ogr/r2/`. Round-1 code paths are not changed.
- One system answers (D2: the three-pipeline comparison stays in the demo UI only).
- **TigerGraph on every answer:** every retrieval tool is one installed GSQL query.
- **No embeddings in the Round-2 path:** text is read from `Document`/`Chunk`
  in the graph (by doc id, or by an installed keyword query). `build.sh`
  therefore needs only TigerGraph and the corpus; the LLM is used only by `run.sh`.
- Deterministic where possible: temperature 0, fixed tool order, stable sorting.

## 2. Graph (additive to Round 1, `graph/schema_r2_answer.gsql`, run after `schema.gsql` + `schema_round2.gsql`)

Round-1 types (Document, OlympicEvent, Games, Sport, Venue, Chunk, embedding
types) and the Round-2 fact layer (Dataset, Source, Entity, Claim, …) are
reused. Added by one local SCHEMA_CHANGE JOB:

| Type | Key / attributes | From |
|---|---|---|
| `Athlete` vertex | `athlete_id` (normalised name), `name` | every medallist name in Olympic infoboxes (gold/silver/bronze incl. ties) |
| `WON` edge Athlete→OlympicEvent | `medal` (gold/silver/bronze), `noc` | infobox `goldNOC`/`silverNOC`/`bronzeNOC` (parser extended) |
| `SourceRecord` vertex | `doc_id`, `title`, `source_name`, `authority`, `published_at` (ISO with offset), `text` | the 39 LA 2028 source records |
| `REPORTS_ON` edge SourceRecord→OlympicEvent | `score` | deterministic link: sport + event name of an LA 2028 event found in the record's title/text |

Infobox facts for every non-Olympic infobox (film, officeholder, person, …):
one `Entity` (entity_id `ent:<doc_id>`, name = page title, entity_type =
infobox type) per document and one `Claim` per infobox key (predicate = key,
numbered keys kept: `predecessor1`, `office2`, …), `ASSERTS` from the Document,
`ABOUT` to the Entity. Money and years are parsed into `value_num` where clean.

**Authority classes** (deterministic, from the `Source:` line, general lexicon):
`official` (signed / jury / certified / register / binding / race director / signed assignment),
`operational` (scoreboard / timing data / registration system / published schedule / access log / control desk),
`secondary` (news / newsletter / bulletin / headlines / media feed / delegation media desk),
`unreliable` (blog / fan / spectator / voice note / volunteer notebook / tourism / ticket email / aggregator / legacy feed / coaching memo).

## 3. Tools (one installed GSQL query each; names are the trace `query`)

| Tool | GSQL query | Params | Returns (rows) |
|---|---|---|---|
| `find_events` | `r2_find_events` | `sport`, `year` (int, 0 = any), `season` ("Summer"/"Winter"/""), `event_contains` | event rows: event_id, doc_id, title, event_name, sport, games, year, date_text, venue, competitors, nations, gold, silver, bronze (with NOCs), synthetic |
| `medals_by_nation` | `r2_medals_by_nation` | `sport`, `year`, `season`, `medal` | noc, count, events (title, doc_id) |
| `event_series` | `r2_event_series` | `event_contains`, `sport`, `season` | one row per edition: year, title, doc_id, nations, competitors, gold; wrapper adds max/min |
| `athlete_medals` | `r2_athlete_medals` | `name` | athlete, medal, noc, event title, year, doc_id |
| `repeat_winners` | `r2_repeat_winners` | `sport`, `medal`, `season` | athlete, event_name, years[], doc_ids[] (same event name, ≥ 2 Games) |
| `entity_facts` | `r2_entity_facts` | `name_contains`, `entity_type` | entity name, type, doc_id, facts {predicate: value} |
| `find_entities` | `r2_find_entities` | `entity_type`, `predicate`, `value_contains` | matching entities with all their facts |
| `source_records` | `r2_source_records` | `event_contains`, `year` | records about the event: doc_id, title, source_name, authority, published_at, text |
| `text_search` | `r2_text_search` | `terms` (list, all must occur, case-insensitive), `limit` | chunks: doc_id, title, chunk_id, text (trimmed) |
| `read_document` | `r2_read_document` | `doc_id` | title + chunks in order (trimmed to a token budget) |

Each tool also exists in `LocalR2Graph` (pure Python over the parsed corpus) with
identical outputs, used by tests and offline checks. A parity test runs both
against the same small fixture where possible (GSQL statically).

Python-side derived operations (`rank` most/fewest, max/min of a series,
counting) are deterministic helpers applied to TigerGraph rows and recorded as
`tigergraph: false` steps.

## 4. Agent (`ogr.r2.agent`)

- LLM planner with native tool calling (provider via `common/llm.py`), temperature 0.
- Loop: up to `R2_MAX_STEPS` (default 8) tool calls, then a forced `finish`.
- `finish(status, answer, explanation, citations)`; `answer` is text or JSON.
- System prompt: general rules only (corpus only; complete lists; statuses
  `answered`/`partial`/`not_in_corpus`; never invent; authority over
  recency; provisional vs official; effective time vs publication time;
  absence of evidence is not evidence of absence; cite doc_ids seen in tool
  results). No question-specific rules, no qids, no answers in code.
- Guards (deterministic): citations restricted to doc_ids returned by tools;
  `not_in_corpus` answer forced to `null`.

## 5. Output (brief format, `ogr.r2.output`)

Answer line: `qid, status, answer, explanation, citations, input_tokens,
output_tokens, latency_ms, trace`. Trace step: `step, tool, tigergraph, query,
params, rows, input_tokens, output_tokens, ms` (+ optional `note`). Token sums of
LLM steps equal the answer totals; written as the code runs.

- `out/r2/tg_query_log.jsonl`: one line per TigerGraph call: `ts` (ISO UTC, ms),
  `qid`, `step`, `query`, `params`, `rows`, `ms`, `ok`.
- `metrics.json`: every field of the brief's example, recomputed from the answer files.
- `graph_counts.json`: vertex and edge counts by type after build.
- Public self-scoring (`ogr.r2.score`): fact-level partial credit, method stated
  in `accuracy_method`.

## 6. Repeatability

`build.sh`, `run.sh` at the repo root; `.env.example` (every key);
`backend/requirements.lock` (exact versions); git tag at submission.

## 7. Dev discipline

The public 50 are split by style into `dev` and `check` (D7); `check` is run
only at the end. The hidden questions are not read by anyone working on the
system; `run.sh` reads them only to answer them.
