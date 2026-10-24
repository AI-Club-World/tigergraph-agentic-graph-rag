# Round 2 — Analysis: gap map and schema strategy

Round-2 statement (verbatim): *"Extend your agent to reason over evolving,
conflicting, and uncertain facts on a harder dataset."*

Status: analysis only. No code, schema or data changed by this document.
Branch: `round-2`. Companion documents: `ROUND2-DESIGN.md` (design),
`ROUND2-PLAN.md` (ordered plan), `ROUND2-INTERVIEW-LOG.md` (gate decisions).

**What is not known yet.** There is no Round-2 guidebook, dataset or deadline.
Everything below that concerns the Round-2 dataset is an assumption and is
labelled **[ASSUMPTION]**. It must be reconciled against the real dataset
before anything relies on it.

**What could not be checked here.** This session has no `.env`, so no
TigerGraph, LLM or embedding endpoint was reachable. Every statement below
comes from reading the code and running the offline test suite (619 backend,
61 frontend, all passing on `a9a2177`). No live run was made.

---

## 1. Where the system assumes facts are static, single-valued and certain

| Layer | Where | Assumption today | Consequence for Round 2 |
|---|---|---|---|
| Corpus record | `data/README.md`; `ingest/infobox.py` `parse_document` | A record has `doc_id, title, url, wikidata_qid, wikipedia_pageid, approx_tokens, text`. No publication time, revision time, author or source class. | There is no observed-time or provenance to reason with. `wikipedia_pageid` and `url` are the only source identity. |
| Infobox parse | `ingest/infobox.py` | One value per field per page (`gold`, `competitors`, `date`, ...). `parse_confidence` (penalties for partial parses) is the only uncertainty signal, and it measures parsing, not truth. | A changed or disputed value has no place to live. Hedged prose ("reportedly 24 nations") is not read. |
| "Timestamp metadata" | `OlympicEvent.date_year/month/day_*`, `Games.year`, `prev/next` years; registry `built_at`, dataset `uploaded_at`, embedding-job `updated_at` | The only per-fact times are **event dates** (valid time of the competition). Ingest records **operational** times (when a dataset or job was built), not when a fact was stated. | Reusable as valid time for events and as observed time for a whole dataset. There is no per-fact observed time. |
| Load | `ingest/load.py` (`upsertVertices`) | One `OlympicEvent` per `event_id`; a second document with the same id silently overwrites the first (last write wins). | Supersession happens by accident, with no record of the loser. Conflicts are erased at load time. |
| Schema | `graph/schema.gsql` | Attributes are scalar or list, with no validity interval, source or confidence. Edges carry no attributes (except `HELD_AT.date_text`). `PREV_EDITION/NEXT_EDITION` are the only temporal relations, and they link editions of an event, not versions of a fact. Types are Olympic-specific (`OlympicEvent`, `Games`, `Sport`, `Venue`). | A fact cannot have two values, a source, a time or a confidence. A non-Olympic dataset gets only `Document/Chunk` (RAG side). |
| Multi-dataset | `ingest/registry.py` | Datasets share one graph. Isolation exists only in a JSON registry of the ids each dataset wrote, used for rebuild and delete. | **No query is scoped by dataset.** P1 searches every chunk in the graph (`p1_rag.py`, `candidate_set=None`), and Q1–Q4 match across datasets. Loading a Round-2 or injected dataset next to Round-1 changes Round-1 retrieval. |
| Intent | `pipelines/p3_agentic/intent.py` `IntentSchema` | `{operation: LOOKUP/COUNT/ARGMAX/TRAVERSE, anchor, constraints, target_field}`. A date constraint means the event's date. | "As of 2018", "before the reallocation", "latest", "originally" have no representation. |
| Entity linking | `agents/entity_linking.py` | One resolved anchor per slot. Dates normalised to one day. | Same, no time scope. |
| Retrieval | Q1–Q5, `agents/*` | Q1 returns every row matching a name, then narrows by Games and day. Q5 is dense top-k only (`q5_hybrid_search` is not hybrid: no BM25). No time filter, no source filter. | Retrieval cannot ask for "the value valid at time t" or "every source about X". |
| Evidence check | `pipelines/p3_agentic/evidence.py` | Binary: sufficient or not (scope coverage, then one LLM groundedness call). | No notion of evidence that is sufficient but disputed, or partial and hedged. |
| Conflict | `agents/answer_resolution.py` `find_conflicts` | The only conflict detection: infobox figure against a prose figure of the **same page**, for `nations/competitors`. Reported in a trace note, answer unchanged. | Across-source and across-time conflicts are not detected. Nothing is resolved or weighed. |
| Answer synthesis | `common/contracts.py` `SHARED_SYSTEM_PROMPT` (CORE-02) | One short answer span plus explanation. The prompt must be byte-identical across P1/P2/P3. | No confidence and no conflicting evidence in the contract. Changing the prompt changes all three pipelines and the Round-1 baseline. |
| Record / trace | `PipelineRecord`, `TraceStep` | Fixed fields; free-text `notes`; `stop_reason` closed vocabulary. | No structured place for time scope, conflicts or confidence. Additive optional fields are safe (pydantic defaults; the frontend ignores unknown keys). |
| Scoring | `eval/scorer.py` | Deterministic EM/F1 plus retrieval P/R. Per-qtype breakdown by label. | No calibration metric (ECE, Brier). New qtypes (`evolving`, `conflicting`, `uncertain`) already work in the per-qtype report. |

## 2. Gaps against the three Round-2 capabilities

**Evolving** (facts change; later supersede earlier; time-scoped questions)
- E1. No observed time (when a statement was made) per document or fact.
- E2. No validity interval per fact; no supersession relation.
- E3. Last-write-wins on load destroys earlier versions.
- E4. No temporal intent ("as of", "before", "after", "latest", "originally", "between") in parse or routing.
- E5. No time-scoped retrieval (Q1–Q5 have no time parameters).

**Conflicting** (sources disagree)
- C1. Source identity is only `doc_id/url`. There is no source class or reliability.
- C2. No representation of two values for one (entity, attribute).
- C3. Conflict detection limited to infobox vs prose on one page.
- C4. No resolution policy: no recency, reliability or corroboration weighing.
- C5. No way to keep losing values as cited conflicting evidence.

**Uncertain** (confidence, partial, hedged)
- U1. `parse_confidence` is the only confidence, and only Q2 uses it (exclusion below 0.9).
- U2. Hedging language in text is not detected.
- U3. No confidence propagation across hops (multi-hop reads Q4 then Q1 with no weights).
- U4. No answer confidence, no calibration, no calibration metric.
- U5. Evidence sufficiency is binary.

**Cross-cutting**
- X1. Graph types and Q1–Q4 are Olympic-specific; the infobox parser is the only structured-ingest path. A non-Olympic Round-2 dataset reaches only P1 and the prose fallbacks of P3. This is the largest risk for "a harder dataset": without a domain-agnostic fact layer, the graph pipelines have nothing to query.
- X2. No dataset scoping at query time (see section 1, Multi-dataset).

## 3. Round-1 behaviour that must be preserved (regression baseline)

| Item | Where it is pinned today | How it is checked |
|---|---|---|
| Three pipelines, same LLM, same embedding model, same answer prompt | `contracts.py` CORE-02; `RunConfig` | `tests/pipelines/*`, `tests/pipelines/p3/test_anti_overfitting.py` |
| P1 unfiltered (no candidate set, no rerank) | `p1_rag.py` AD-9 | `tests/pipelines/test_p1_unfiltered.py` |
| P2 = intent + one query, no loop | `p2_graphrag.py` | `tests/pipelines/test_p2.py` |
| P3 routing, stop reasons (closed vocabulary), trace token reconciliation | `router.py`, `stopping.py`, `trace.py` | `test_router.py`, `test_loop*.py`, `test_token_reconciliation.py` |
| `PipelineRecord` / `TraceStep` shape | `contracts.py`, `frontend/src/types.ts` | API and frontend tests |
| No qtype read, no eval strings in the answer path | anti-overfitting tests | same |
| Scored baseline r5 public-100 (RAG 0.59, GraphRAG 0.63, Agentic 0.98 EM) | `out/` run files (not in this checkout) | live run only |

Offline: 619 backend and 61 frontend tests pass on `a9a2177`. Live baseline:
**not run in this session** (no credentials). It must be re-run before the
first Round-2 change that touches the answer path, and after each major change.

**Note.** The brief refers to a Round-1 trace/output format "built against TG
Multihop30". No file or reference by that name exists in this repository;
the Round-1 sets here are `eval_public.jsonl` (100) and `eval_hidden.jsonl`
(50). This needs reconciling with the user (see the interview log).

---

## 4. Schema strategy: one graph with dataset scoping (A) or one graph per dataset (B)

### Option A — one graph, every vertex and edge scoped to a dataset

Today's layout is already "one graph, many datasets", tracked in the registry
but **not scoped at query time**. Option A finishes that design: an explicit
`Dataset` vertex, membership edges, and every query takes a dataset scope.

### Option B — one TigerGraph graph per dataset

Each dataset gets its own graph (for example `OlympicGraphRAG`,
`R2_<dataset>`). Queries are installed per graph, and the client picks the graph per run.

### Evaluation

| Criterion | A: one graph, scoped | B: graph per dataset |
|---|---|---|
| **Query isolation / correctness** | Correct only if *every* query filters by dataset. One forgotten filter mixes datasets silently. Testable: one fixture per query that loads two datasets. | Isolated by construction. |
| **Traversal performance** | Scoping costs one extra hop or attribute check per seed set. Small at this size (about 30k vertices). | No extra filter. |
| **Vector index (HNSW)** | Embedding types are **global** (`add_vectors` is a GLOBAL schema change job). One index per model holds every dataset's chunks. Scoped search uses the `candidate_set` path Q5 already has (filtered HNSW), seeded from the dataset's chunks. Recall under a filter needs a check once Round-2 data is loaded. | With today's global types, two graphs **share** the same `Embedding_*` vertex types, and so the same index: no isolation unless each graph gets local embedding types (five types × N graphs, each with its own index and memory). |
| **Ingest / re-ingest** | Additive: a new dataset loads next to the others. Rebuild per dataset already exists (`removable_ids`). | Clean: drop one graph, reload it. Every graph needs its own query install (about 1 minute per query, which blocks other operations). |
| **Cross-dataset comparison** | Round-1 baseline and Round-2 in one workspace; switch by scope. | Switch graph per run; also fine. |
| **Embedding switching** (per-model types, max 2 models, cross-model block, no cascade deletes) | Unchanged: one `EmbeddingStore`, one cap, one coverage set. Coverage must become per dataset (a model can be complete for one dataset and not another), which extends `EmbeddingStore` by a key. | The store, cap, coverage and eviction logic all become per graph. The max-2 cap is per workspace (memory) or per graph: a design decision and a rewrite of `embedding_index.py`. Highest regression risk. |
| **TigerGraph limits** | One schema; additive changes through a local or global SCHEMA_CHANGE JOB, without dropping data. Whether installed queries need reinstalling after a type is added must be checked on Savanna **[to verify]**. | More graphs and query installs on one workspace. Query text hard-codes `FOR GRAPH OlympicGraphRAG`, so it needs templating. |
| **Extensibility when the real dataset arrives** | A new adapter writes into generic types under a new `Dataset`. Reasoning code is unchanged. | Same, plus a new graph and query install per dataset. |
| **Effort** | Medium: about 6 queries gain a scope parameter, plus membership edges and backfill for Round-1 (no re-embedding). | High: per-graph client, query templating, per-graph embedding store and registry. |

### Decision (recommended): **A — one graph, explicit dataset scoping**, with these conditions

1. **Round-1 types stay untouched.** No attribute is added to `Document`, `OlympicEvent`, `Chunk` or the embedding types. Scoping is by **edges** from a new `Dataset` vertex (`IN_DATASET`), backfilled for Round-1 from the registry's id lists. No re-ingest and no re-embedding.
2. **Round-1 queries Q1–Q5 stay as installed.** Scoped variants are new queries, so the Round-1 code path cannot regress. Round-1 runs keep using Q1–Q5 while only the Round-1 dataset is loaded.
3. **A generic fact layer is added beside the Olympic types** (section 5), so a non-Olympic Round-2 dataset reaches the graph pipelines.
4. **Escape hatch to B.** If the real Round-2 dataset needs a vector dimension no existing model has, or filtered HNSW recall measures poorly at its size, a separate graph for it is still possible because the generic types do not depend on the Olympic ones.

Why not B: its isolation advantage disappears for the vector index unless the
embedding types are duplicated per graph, and duplicating them breaks the
settled embedding-switching design (one store, max 2 models), which has the
highest regression cost of anything in this list.

## 5. Can time, provenance and confidence fit the current schema?

| Need | Inside the current schema? | Why |
|---|---|---|
| Valid time of an *event* | Yes: `date_year/month/day_*` | Already typed INTs. |
| Observed time of a document (when it was stated) | **No** | `Document` has no time attribute. Can be carried as text in the chunk header (visible to all pipelines), but not queried. |
| Two values for one (entity, attribute) | **No** | `OlympicEvent` attributes are single-valued; upsert overwrites. |
| Source / reliability | Partly: `Document.url`, `wikipedia_pageid` | No source class, no reliability. |
| Confidence | Partly: `OlympicEvent.parse_confidence` | Parse quality only, one per event, not per fact. |
| Supersession / contradiction | **No** | No edge type; `PREV/NEXT_EDITION` relate events, not claims. |

**Conclusion.** Valid time for Olympic events can be reused as is. Everything
else needs **additive** types. Overloading existing attributes, or keeping
facts in a sidecar file outside TigerGraph, would avoid a schema change but
take the reasoning out of the graph. That is the weakest option for a
TigerGraph GraphRAG entry, and it would not be queryable by the agent's graph
tools.

Proposed additive types (detailed in `ROUND2-DESIGN.md` §2). None of them
changes an existing type:

```
VERTEX Dataset   (dataset_id, title, adapter, observed_at_default)
VERTEX Source    (source_id, name, source_class, reliability_prior, reliability_est)
VERTEX Entity    (entity_id, name, entity_type)            // domain-agnostic subject
VERTEX Claim     (claim_id, predicate, value_text, value_num, valid_from, valid_to,
                  observed_at, extraction_conf, hedged, hedge_terms, claim_conf)
EDGE   IN_DATASET     (Document|Claim|Source|Entity -> Dataset)
EDGE   ASSERTS        (Document -> Claim, chunk_id)
EDGE   FROM_SOURCE    (Document -> Source)
EDGE   ABOUT          (Claim -> Entity | OlympicEvent)
EDGE   SUPERSEDES     (Claim -> Claim, reason)
EDGE   CONTRADICTS    (Claim -> Claim)
EDGE   SAME_AS        (Entity -> OlympicEvent)               // bridge to Round-1 entities
```

Applying these is a **schema change** (additive, through a SCHEMA_CHANGE JOB,
with no `DROP GRAPH`). Under the standing rules it is gated: gate G1 in the
interview log.
