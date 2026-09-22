---
path: specs/001-graphrag-foundation/implementation-plan-GRAPH.md
implements_tasks: GRAPH
level: implementation-plan
derived_from: TECHNICAL-SPEC.md, ARCHITECTURE-SPEC.md, APPLICATION-SPEC.md
cache: volatile
tier: LOCALISED
gate: G0 -> G2
status: approved
plan_id: PLAN-001
task_tracker: ./task.md
sub_plans: []
---

# GraphRAG (P2 pipeline + shared foundation) — Implementation Plan

**Module name**: taken verbatim from MODULE-BREAKDOWN.md § "Module: GraphRAG (P2 pipeline + shared foundation)"
**Source spec**: TECHNICAL-SPEC §2, §3, §8.2, §11 · ARCHITECTURE-SPEC §6, §7 · APPLICATION-SPEC §3
**Workspace**: `backend/src/ogr/ingest/`, `backend/src/ogr/graph/`, `backend/src/ogr/pipelines/p2_graphrag.py`
**Task tracker**: [task.md](./task.md)
**Stack (fixed)**: Python · pyTigerGraph (async) · sentence-transformers · **TigerGraph Savanna — mandatory store for both vectors and graph; no FAISS, Chroma, pgvector or any external index anywhere in the system**. No LangChain in this module — ingestion and GSQL are deterministic and LangChain adds nothing but indirection here.
**Effort (T1 scope)**: 15 pt of the 60 pt Round-1 target · **owns the critical path**

> This module owns schema, ingestion, embeddings and the query library that
> PLAN-002 and PLAN-003 both consume. Build order respects that even though
> MODULE-BREAKDOWN tracks it as one of four peers.

---

## Research Summary

Every claim below was established by parsing `corpus.jsonl` (2,951 records) and
both eval files. Numbers the specs asserted were checked, not assumed.

- **Current state**: greenfield; no schema, no TigerGraph workspace provisioned
  as of writing. Nothing verified against a live instance yet.
- **Gaps identified**: **9 distinct** across 4 groups.

**Spec claims confirmed against the data** — these need no further validation:
2,951 documents · 5,466,414 tokens by `approx_tokens` · 73.3% Olympic-event
infoboxes (2,162), 18.5% film (546), 8.2% other · `doc_id == wikidata_qid` for
all records, zero duplicates · all 518 distinct `gold_doc_ids` present and all
Olympic-event infoboxes · 303 distinct venues, "Olympic Stadium" hosting 115 ·
23.0% of venue+date pairs non-unique (353/1,538).

**Findings that change the plan:**

- **There is no `sport` field in any infobox.** The `Sport` vertex and the
  `sport` parameter on Q2/Q3 have no source attribute. Sport is derivable from
  the title prefix `<Sport> at the <Games>`, which matches **2,162/2,162** and
  yields **41** distinct sports. Derivation rule must be written into the parser.
- **Dates live in two fields with heterogeneous formats.** `date` on 57.9%,
  `dates` on 41.1%; observed forms include `6 to 8 August`, `February 22, 1992`,
  `23–26 August`, `August 21–22`, and
  `August 18 (heats)August 20 (semifinals)August 21 (final)`. Only **81%**
  carry a year. Questions always supply one. **No spec task normalizes either
  side**, and multi_hop (28) + temporal (22) = **50 of 100 public questions**
  depend on date matching. This is the largest accuracy risk in the build.
- **`prev` and `next` are already infobox fields** (93.4% / 97.6%), as bare
  years (`"2008"`, `"2016"`). `PREV_EDITION` is a deterministic join on
  (sport, event name, prev-year, season), not the inference problem
  ARCHITECTURE-SPEC §13 anticipated. GRAPH-03 drops from M to S and its risk row
  is retired.
- **The venue-disambiguation mitigation in ARCHITECTURE-SPEC §13 does not work.**
  Filtering venue+date by Games year changes non-uniqueness from 353/1,538
  (23.0%) to 353/1,540 (**22.9%**) — it resolves nothing, because same-venue,
  same-date collisions occur *within* a single Games by construction. The real
  discriminators are sport and event name.
- **Venue matching needs longest-match.** Substring matching finds
  `Olympic Oval` inside `Richmond Olympic Oval`, `Riocentro` inside
  `Riocentro – Pavilion 4`, `Sydney` inside `Sydney International Shooting
  Centre`. The vocabulary is closed at 303 entries, so longest-match is trivial
  and removes a whole class of silent wrong answers.
- **`competitors` is non-integer in 23 of 2,130 events** (1.1%): `23 teams`,
  `32 (16 pairs)`, `75 (10 teams)`. TECHNICAL-SPEC §12's "fail loudly" would
  drop 23 team events out of every aggregation. `nations` is integer in
  2,128/2,128.
- **Third-place ties are unmodelled.** `bronze2` / `bronzeNOC2` appear on ~13%
  of Olympic events; the schema has a single `bronze`.
- **`win_value` (64%) and `win_label` (21.5%) are real corpus fields** — the
  prior audit's "unused attribute" finding is withdrawn. Keep them.
- **Games is a 21-value closed vocabulary spanning 1900–2022**, not 1987–2022 as
  APPLICATION-SPEC §1 states (1900 Summer ×1 and 1984 Summer ×2 are outliers).
- **The aggregation/superlative thesis is proven.** A ~30-line infobox parser
  with no graph reproduces pub-001 (biathlon 2018, competitors > 73 → **5**) and
  the athletics-2008 superlative (→ **Men's marathon**, 95 competitors) exactly.
- **The vector path is the largest technical unknown.** `tigergraph-mcp` requires
  TigerGraph 4.1+, with 4.2+ recommended for TigerVector. The community skills
  pack (133 skills) contains **no TigerVector, vector-index or
  `/restpp/vector/status` skill** — the one area with a documented async-lag
  gotcha is the one area with no reference material.

> Not read, therefore not asserted: actual `vectorSearch()` syntax on the
> provisioned Savanna version, and real GSQL install timing.
> `[NEEDS CLARIFICATION]` — resolved by the Group 0 spike, not by inference.

---

## Design Decisions Required Before Implementation

### DP-1 — Date normalization representation

**Gap**: two source fields, heterogeneous formats, 19% missing years; nothing in
any spec defines a normalized form. Blocks 50% of the public question set.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Parse at ingest into four typed attributes on `OlympicEvent`: `date_month` INT, `date_day_start` INT, `date_day_end` INT, `date_year` INT (from `games` when absent); keep `date_text` verbatim for display; apply the **same** normalizer to question text | M | No | Date match becomes a native predicate, same idiom as the INT casting of `competitors`; one normalizer, two callers |
| B | Store `date_text` only, match by string similarity at query time | S | No | Fails on `23–26 August` vs `23 to 26 August`; pushes a parse into every query |
| C | ISO 8601 range string `YYYY-MM-DD/YYYY-MM-DD` | M | No | Clean, but multi-session dates (`August 18 (heats)…`) don't fit a single range and lose their parts |

**Recommendation**: Option A — it mirrors the highest-leverage decision already
in the schema (typed INTs as native predicates) and is the only option that
makes the same code normalize both sides.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-2 — Non-integer `competitors` policy

**Gap**: TECHNICAL-SPEC §12 says fail loudly; 23 real team events would be lost.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Extract leading integer; set `parse_confidence < 1.0`; store the raw string in `competitors_text`; Q2/Q3 exclude sub-threshold rows **and return the excluded count** | S | No | Gives `parse_confidence` the consumer it has lacked; the excluded count becomes a demo asset — the system states what it could not parse |
| B | Fail loudly, drop the 23 | S | No | Silently wrong aggregates for team sports; contradicts the spec's own "no silent wrong counts" goal |
| C | Treat `23 teams` as 23 with full confidence | S | No | Conflates teams and competitors — a wrong answer with no signal |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-3 — Q5 vertex-type parameter vs a sixth query

**Gap**: both `OlympicEvent` and `Chunk` carry `emb`. Q5's signature
`hybrid_search(query_vector, k, candidate_set)` cannot say which to search.
AD-7 fixes the library at exactly five installed queries.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Add `vtype` parameter to Q5, branch inside the query body | S | No | Preserves AD-7 verbatim; one `IF` block; one install |
| B | Q5 for chunks, Q6 for events | S | No | Breaks AD-7's "exactly five"; a second ~1-min install that blocks concurrent ops |
| C | Search both, merge, tag results by type | M | No | Doubles P1's retrieved set and muddies the unfiltered-ceiling argument in AD-9 |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-4 — Venue disambiguation policy, given that the specced mitigation fails

**Gap**: adding Games year leaves 22.9% of venue+date pairs ambiguous. 28 of 100
public and 10 of 50 hidden questions are venue-anchored.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Traverse venue → filter by normalized date (DP-1) → if >1 event remains, return a **disambiguation request** naming the candidates, and count how often it fires | S | No | Honest, measurable, and the counter is itself a finding for the writeup; guessing on 23% would poison the accuracy number |
| B | Return the first/highest-similarity candidate | S | No | Converts a known ambiguity into a silent wrong answer on a scored question |
| C | Add sport/event-name inference from question context to break ties | M | No | Higher ceiling, but it is LLM inference on the answer path — raises the FR-11/NFR-7 overfitting question |

**Recommendation**: Option A for T0; C is the natural Round-2 extension.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-5 — Bronze ties (`bronze2` / `bronzeNOC2`, ~13% of events)

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | `bronze` becomes a `SET<STRING>` / list attribute holding both where present | S | No | Correct on 13% of events for one schema-line change |
| B | Add `bronze2` / `bronzeNOC2` as separate attributes | S | No | Mirrors the source but every consumer must remember to check two fields |
| C | Ignore `bronze2` | — | No | Wrong on ~280 events; cheap to avoid |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

---

## Open Questions (non-blocking)

- Whether to store `wikipedia_pageid` on `Document` (corpus provides it; useful
  for citation links, costs nothing).
- Loading mechanism: CSV loading job vs REST upsert via pyTigerGraph. Either
  works at 2,951 documents.
- Whether to keep the 3 outlier Games (1900 Summer ×1, 1984 Summer ×2).

---

## Proposed Changes

Ordered by dependency — lower-level components first.

### Group 0 — Vector spike (1 pt) · **first hour, blocks everything**

#### ADD `scripts/spike_vector.py`
- Provision Savanna workspace; install a 2-vertex toy schema with a 384-dim
  COSINE `emb`; load 20 documents; embed with all-MiniLM-L6-v2; poll
  `/restpp/vector/status` until `Ready_for_query`; run one `vectorSearch()`.
- Records observed install time and index-lag duration in `docs/spike-notes.md`.
- **Requirement**: TECHNICAL-SPEC §11 vector-readiness gate · **Gate**: `G0`
- **Rollback**: if `vectorSearch()` is unavailable on the provisioned version,
  **stop and escalate**. It invalidates Q5, P1 and AGENT-05 across three plans.
  **There is no external vector-store fallback** — TigerGraph holds both the
  vectors and the graph, and that is a hackathon eligibility condition, not a
  preference. The only permitted fallback is a local Community Edition 4.2+
  instance, which is why the spike runs in the first hour rather than day 2.

### Group 1 — Schema (2 pt)

#### ADD `backend/src/ogr/graph/schema.gsql`
- Vertices per TECHNICAL-SPEC §2.1 with the amendments from DP-1 (date attrs),
  DP-2 (`competitors_text`), DP-5 (bronze as set). `Run`/`Step` **omitted** —
  cut under T0.
- Edge endpoints pinned explicitly (the spec leaves four undirected):
  `DESCRIBES` Document→OlympicEvent · `AT_GAMES` OlympicEvent→Games ·
  `IN_SPORT` OlympicEvent→Sport · `HELD_AT` OlympicEvent→Venue ·
  `PREV_EDITION`/`NEXT_EDITION` OlympicEvent↔OlympicEvent ·
  `HAS_CHUNK` Document→Chunk.
- Idempotent install (drop-if-exists guard).
- **Requirement**: `FR-11` foundation · **Gate**: `G0`
- **Rollback**: `DROP ALL` and reinstall; no data loaded yet.

### Group 2 — Ingestion (4 pt)

#### ADD `backend/src/ogr/ingest/parse_infobox.py`
- Parse `[Infobox <type>]` header + two-space-indented `key: value` block.
- Sport from title prefix (`<Sport> at the …`, 2,162/2,162 coverage).
- `competitors` per DP-2; `nations` direct INT cast.
- Coverage report to `out/ingest-coverage.md`: per-field presence, parse
  confidence distribution, and the list of 23 non-integer `competitors`.
- **Requirement**: TECHNICAL-SPEC §2.3, §12 · **Gate**: `G1`
- **Rollback**: parser is pure; re-run over corpus, reload.

#### ADD `backend/src/ogr/common/dates.py`
- Normalizer per DP-1, shared by ingestion **and** question parsing (PLAN-003
  imports it). Handles `N to M Month`, `N–M Month`, `Month N–M`,
  `Month N, YYYY`, `N Month YYYY`, and multi-session concatenations.
- **Requirement**: temporal + multi_hop accuracy · **Gate**: `G1`
- **Rollback**: revert; temporal/multi_hop degrade to text match.

#### ADD `backend/src/ogr/ingest/load.py`
- Upsert Document, OlympicEvent, Games (21), Sport (41), Venue (303) and all
  edges. `PREV_EDITION`/`NEXT_EDITION` resolved from the `prev`/`next` year
  fields by (sport, event name, year, season) join; resolution-rate report.
- **Requirement**: `FR-11` · **Gate**: `G1`
- **Rollback**: truncate graph, re-run; ingest is idempotent by `doc_id`.

#### ADD `backend/src/ogr/ingest/chunk_embed.py`
- Chunk and embed **all 2,951 documents**, not only the Olympic subset. This is
  load-bearing for AD-9: if only parsed Olympic docs enter the vector index, P1
  is implicitly type-filtered by ingestion and the honesty argument collapses.
- Local all-MiniLM-L6-v2, 384-dim, COSINE.
- **Requirement**: `AD-9`, `AD-6` · **Gate**: `G1`
- **Rollback**: re-embed; deterministic, so re-runs are identical.

#### ADD `backend/src/ogr/graph/vector_status.py`
- Poll `/restpp/vector/status` for `Ready_for_query`; hard gate that blocks any
  benchmark start.
- **Requirement**: TECHNICAL-SPEC §11 · **Gate**: `G1`
- **Rollback**: none needed; failing closed is the correct behaviour.

### Group 3 — Query library (4 pt)

#### ADD `backend/src/ogr/graph/queries/q1_lookup.gsql` … `q5_hybrid_search.gsql`
- Q1 `lookup(title | event_id, target_field)`.
- Q2 `count_where(anchor_sport, anchor_games, anchor_venue, constraints_json, field)`
  — widened per the cross-module intent-schema finding; `SumAccum<INT>`.
- Q3 `argmax(anchor_sport, anchor_games, anchor_venue, field)` — `HeapAccum` top-3.
- Q4 `traverse(anchor, edge_type, hops)`.
- Q5 `hybrid_search(query_vector, k, vtype, candidate_set)` per DP-3.
- Prototype via `INTERPRET QUERY`; install all five once, near the end.
- **Requirement**: TECHNICAL-SPEC §3, `AD-7` · **Gate**: `G1`
- **Rollback**: `INTERPRET` versions remain callable if install fails.

#### ADD `backend/src/ogr/graph/client.py`
- pyTigerGraph async wrapper; token/latency capture at the lowest invocation
  point (NFR-3), emitting into the shared `PipelineRecord` shape from PLAN-004.
- **Requirement**: `NFR-3` · **Gate**: `G1`
- **Rollback**: revert to sync calls.

#### ADD `backend/src/ogr/ingest/progress.py` *(new — required by the 3-column build UI)*

- Every ingestion and query-library step emits a `BuildEvent`
  `{stage, pipeline_affected, status, items_done, items_total, elapsed_ms, tokens, note}`
  onto an asyncio queue the API layer drains as SSE (PLAN-004 Group 5).
- `pipeline_affected` is a **list**, because the stages are shared: chunk+embed
  feeds `["rag", "graphrag", "agentic"]`, schema+parse+load feeds
  `["graphrag", "agentic"]`, query-library install feeds all three. This is what
  makes an honest three-column build view possible without inventing three
  separate builds (PLAN-004 DP-5).
- `tokens` is **0** for every ingestion stage. Ingestion uses a local embedding
  model and deterministic parsing — there is no LLM in this path (AD-6), so the
  build columns report wall-time, document counts and vertex/edge counts, not
  token spend. Displaying a fabricated build-token figure would misrepresent the
  cost comparison the whole submission is built on.
- **Requirement**: new UI requirement; `NFR-3` · **Gate**: `G1`
- **Rollback**: emitter is fire-and-forget; drop the queue and ingestion still
  runs headless.

### Group 4 — P2 GraphRAG pipeline (2 pt)

#### ADD `backend/src/ogr/pipelines/p2_graphrag.py`
- **Routing (revised — PLAT-07)**: P2 reuses the **same intent parser as P3**,
  then executes exactly one query with **no evidence check, no fallback and no
  loop**. The originally specified "fixed question-type → Q1/Q4/Q5 table" is not
  implementable: `qtype` is an eval-set label and NFR-7 forbids question-template
  regex in the answer path, so the specified routing must either read the test
  label or pattern-match the question. Sharing the parser also makes the
  comparison a clean ablation — P1 removes the graph, P2 removes the loop, P3 has
  both — instead of three systems differing in several ways at once.
- Generation uses the shared answer contract (`CORE-02`), prompt byte-identical
  to P1's and P3's apart from retrieved context.
- Venue disambiguation per DP-4.
- Single LLM generation call with graph context; entity/relationship citations
  carrying both `source_id` and `chunk_id` per PLAN-004 DP-1.
- **Requirement**: `FR-2`, `FR-4`, `FR-10` · **Gate**: `G2`
- **Rollback**: revert; P1 and P3 unaffected (fault isolation, NFR-2).

---

## Verification Plan

### Automated

```
pytest -q backend/tests/ingest tests/graph tests/pipelines/test_p2.py
python -m ogr.cli ingest --dry-run --report out/ingest-coverage.md
```

| Group | New tests | Command | Verdict |
|---|---|---|---|
| 0 | `test_vector_search_returns_k_results` | `python scripts/spike_vector.py` | `unmeasured` |
| 1 | `test_schema_installs_idempotently` | `pytest -q backend/tests/graph/test_schema.py` | `unmeasured` |
| 2 | `test_sport_derivable_for_all_olympic_docs` (expect 2162/2162), `test_competitors_int_cast` (expect 2107 clean, 23 flagged), `test_date_normalizer_covers_observed_formats`, `test_prev_next_resolution_rate` | `pytest -q backend/tests/ingest` | `unmeasured` |
| 3 | `test_q2_replicates_pub001` (expect **5**), `test_q3_replicates_athletics_2008` (expect Men's marathon), `test_q5_vtype_switch` | `pytest -q backend/tests/graph/test_queries.py` | `unmeasured` |
| 4 | `test_p2_conforms_to_pipeline_record`, `test_venue_ambiguity_returns_disambiguation` | `pytest -q backend/tests/pipelines/test_p2.py` | `unmeasured` |

- The Group 3 tests are **replication tests against known gold answers already
  verified outside the graph**. If the graph disagrees with the Python parser,
  the graph is wrong — that is the point of having both.
- **Holdout**: no test in this module may read `acceptance/holdout/`.
- **Unmeasured is a real outcome.**

### Manual

- Read 5 random ingested `OlympicEvent` vertices in GraphStudio against their
  source documents; confirm every attribute matches.
- Confirm `out/ingest-coverage.md` reports ≥98% presence for `competitors`,
  `nations`, `games`, `gold` and ≥96% for `venue`.

---

## Execution Order

1. Group 0 → **verify**: `vectorSearch()` returns results on the toy schema
2. Group 1 → **verify**: schema installs twice cleanly (**G0**)
3. Group 2 → **verify**: coverage report thresholds met; 2,951 docs embedded;
   `Ready_for_query` observed
4. Group 3 → **verify**: pub-001 and the athletics-2008 superlative replicate
   through GSQL, not just through Python (**G1**)
5. Group 4 → **verify**: P2 output validates against `PipelineRecord` (**G2**)
6. Final re-analysis pass: re-run the coverage report after any parser change

A group that fails its check stops the sequence; it does not proceed on a
partial pass.

---

## Sub-plan externalization

| Sub-plan | Scope | File | Status |
|---|---|---|---|
| PLAN-001-a | Group 2 ingestion, if the parser needs its own task breakdown | ./plans/group-2-ingest.md | not created |

---

## Stop conditions

- `vectorSearch()` unavailable on the provisioned TigerGraph version (Group 0)
  — escalate immediately; it invalidates work in two other plans
- Any DP reached while unselected
- GSQL install blocks operations for materially longer than ~1 min each —
  fall back to `INTERPRET QUERY` for the whole run and record it
- A change would require editing a replication test to make the build pass
- Parser coverage falls below the thresholds above and the fix is to loosen the
  threshold rather than the parser
- Iteration, wall-clock or budget cap reached
