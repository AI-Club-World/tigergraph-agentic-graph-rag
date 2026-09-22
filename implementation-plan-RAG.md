---
path: specs/002-rag-pipeline/implementation-plan-RAG.md
implements_tasks: RAG
level: implementation-plan
derived_from: TECHNICAL-SPEC.md, ARCHITECTURE-SPEC.md, APPLICATION-SPEC.md
cache: volatile
tier: LOCALISED
gate: G1 -> G2
status: approved
plan_id: PLAN-002
task_tracker: ./task.md
sub_plans: []
---

# RAG (P1 pipeline) — Implementation Plan

**Module name**: taken verbatim from MODULE-BREAKDOWN.md § "Module: RAG (P1 pipeline)"
**Source spec**: TECHNICAL-SPEC §8.1 · ARCHITECTURE-SPEC §2, AD-9 · APPLICATION-SPEC FR-2/4/10
**Workspace**: `backend/src/ogr/pipelines/p1_rag.py`
**Task tracker**: [task.md](./task.md)
**Stack (fixed)**: Python · LangChain for the generation call only · Q5 called directly through `backend/src/ogr/graph/client.py`
**Effort (T1 scope)**: 3 pt of the 60 pt Round-1 target

> This is the smallest module and the easiest to get subtly wrong. Its value to
> the submission is entirely in being an **honest** baseline: AD-9 says P1's
> retrieval ceiling must be visible, not masked. Every optimisation instinct
> applied here damages the thesis.

---

## Research Summary

- **Current state**: greenfield. Blocked on PLAN-001 Groups 2–3 (chunks embedded,
  Q5 installed, vector index `Ready_for_query`) and on PLAN-004 Group 0
  (record contract).
- **Gaps identified**: **4 distinct** across 2 groups.
- Findings that change the plan:
  - **A contradiction exists between the specs about what P1 cites.**
    TECHNICAL-SPEC §6.2 types `source_id` as `doc_id` (wikidata QID);
    MODULE-BREAKDOWN RAG-04 says "chunk-id citations, scorable as a set against
    `gold_doc_ids`". Chunk IDs are not QIDs, so RAG-04's deliverable **cannot be
    scored as written**. Since all 518 distinct gold docs are corpus `doc_id`s
    and `doc_id == wikidata_qid` for all 2,951 records, the scored identifier
    must be the parent document. Resolved by PLAN-004 DP-1 (dual field); this
    plan consumes that decision and must not re-litigate it.
  - **The corpus is 26.7% non-Olympic** (546 film, 73 officeholder, 65 person,
    25 tennis tournament, 18 with no infobox, and a long tail). Those documents
    are what make P1's unfiltered retrieval genuinely lossy — retrieving a film
    infobox for an Olympic question is the observable ceiling the demo needs.
    If ingestion embeds only Olympic documents, P1 is silently type-filtered and
    AD-9 is violated. **Enforced upstream in PLAN-001 Group 2; asserted here.**
  - **Chunking parameters are unspecified anywhere.** Corpus documents average
    1,852 tokens (median 1,032, max 26,874), so chunk size materially changes
    what P1 can retrieve.
  - **`k` is undefined across all specs**, appearing in Recall@k / Precision@k
    five times without a value.
  - `approx_tokens` is supplied per document, so chunk-count estimates need no
    tokenizer pass at planning time: ~18,000 chunks at 300 tokens.
  - **LangChain is now in the stack, and its convenience retrievers are a
    direct threat to AD-9.** Several LangChain retriever wrappers apply
    behaviour P1 must not have — `ContextualCompressionRetriever` and any
    reranker-backed retriever filter results, `MultiQueryRetriever` rewrites the
    query, `EnsembleRetriever` fuses rankings. Any of these silently converts
    the honest baseline into a tuned one, and the change would be a one-line
    diff an assistant makes without comment. P1 calls Q5 through
    `backend/src/ogr/graph/client.py` directly; LangChain's role in this module is the
    generation call and its usage callback, nothing else.

> Not read, therefore not asserted: actual retrieval quality at any k. That is
> measured at G3, not predicted here.

---

## Design Decisions Required Before Implementation

### DP-1 — Chunking parameters and `k`

**Gap**: neither chunk size, overlap, nor `k` appears in any spec, yet all three
determine P1's measured ceiling — the number the whole comparison rests on.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | 300-token chunks, 50-token overlap, `k = 10`, recorded in `run_config` | S | No | ~18k chunks, comfortably within Community Edition; k=10 against a median of 2 gold docs gives P1 a genuinely fair shot on lookup while still failing structurally on aggregation (median 11+ gold docs) |
| B | 1,000-token chunks, `k = 5` | S | No | Fewer, larger chunks inflate P1's input tokens and blur the token-efficiency comparison |
| C | Tune k empirically, report the best | M | No | Tuning P1 on the eval set is the overfitting failure ARCHITECTURE-SPEC §13 names first |

**Recommendation**: Option A, fixed before the first run and never tuned against
eval results. Sweeping k is a *demo artefact* (US-4: "no value of k fixes this"),
not a tuning activity — run it once, as an appendix, after G5.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

### DP-2 — What P1 retrieves over

**Gap**: both `Chunk` and `OlympicEvent` carry `emb`. Q5 gains a `vtype`
parameter (PLAN-001 DP-3), so P1 must choose.

| # | Approach | Cost | Breaking? | Notes |
|---|---|---|---|---|
| **A** *(Recommended)* | Chunks only, across all 2,951 documents, no type filtering | S | No | This is textbook RAG and exactly what AD-9 describes; the non-Olympic 26.7% stays reachable, which is the point |
| B | Event vectors only | S | No | Gives P1 structured records it would not have in reality — flatters the baseline and weakens the comparison |
| C | Both, merged | M | No | Muddies attribution of P1's failures between text and structure |

**Recommendation**: Option A.
**Selected**: **A** · **by**: `team lead` · **on**: `2026-09-21`

---

## Open Questions (non-blocking)

- Prompt wording for the single generation call. Keep it plain; an elaborate
  prompt here is another way of quietly optimising the baseline.
- Whether to record the retrieved chunk text in the batch record (useful for
  drill-down, costs disk).

---

## Proposed Changes

### Group 1 — Retrieval and generation (2 pt)

#### ADD `backend/src/ogr/pipelines/p1_rag.py`
- Generation uses the **shared answer contract** (`CORE-02`): returns
  `{"answer": "<short span>", "explanation": "<prose with citations>"}`, with a
  prompt byte-identical to P2's and P3's apart from retrieved context. EM and F1
  score `answer` only. Without this, a correct P1 answer phrased as a sentence
  scores EM = 0 and the comparison is flat rather than informative.
- Q5 call with `vtype="Chunk"`, `k` from `run_config`, **no `candidate_set`, no
  type predicate, no re-ranking, no relevance threshold**.
- Single LLM generation call with retrieved chunks as context.
- Citations: `source_id` = parent `doc_id` via `HAS_CHUNK`, `chunk_id` retained
  for display, per PLAN-004 DP-1.
- `chunks_returned` and `citations_count` populated (guidebook trace
  requirement).
- Token and latency capture at the invocation layer, not estimated post-hoc.
- **Requirement**: `FR-2`, `FR-4`, `FR-10`, `NFR-3`, `AD-9` · **Gate**: `G2`
- **Rollback**: revert the file; P2 and P3 unaffected by design (NFR-2).

### Group 2 — Ceiling protection (1 pt)

#### ADD `backend/tests/pipelines/test_p1_unfiltered.py`
- Asserts, by inspecting the Q5 call arguments, that P1 passes no
  `candidate_set`, applies no post-retrieval filter, and performs no re-rank.
- Asserts the vector index contains chunks from non-Olympic documents — the
  concrete check that ingestion did not silently type-filter P1.
- This test exists to stop a well-meaning code assistant from "improving" P1.
  It protects AD-9 from the inside.
- **Requirement**: `AD-9` · **Gate**: `G2`
- **Rollback**: none — if this test is the thing being removed, stop and escalate.

#### MODIFY `README.md`
- One paragraph stating plainly that P1 is unfiltered by design and why, so the
  three-way comparison reads as honest rather than rigged. Under Round 1 there
  is no writeup deliverable, so the README carries this.
- **Requirement**: `AD-9` · **Gate**: `G6`
- **Rollback**: n/a.

---

## Verification Plan

### Automated

```
pytest -q backend/tests/pipelines/test_p1.py tests/pipelines/test_p1_unfiltered.py
python -m ogr.cli ask "How many nations competed in Sailing at the 2016 Summer Olympics – Women's RS:X?" --pipelines rag
```

| Group | New tests | Command | Verdict |
|---|---|---|---|
| 1 | `test_p1_conforms_to_pipeline_record`, `test_p1_citations_resolve_to_doc_ids`, `test_p1_tokens_captured_not_estimated` | `pytest -q backend/tests/pipelines/test_p1.py` | `unmeasured` |
| 2 | `test_p1_passes_no_candidate_set`, `test_index_contains_non_olympic_chunks` | `pytest -q backend/tests/pipelines/test_p1_unfiltered.py` | `unmeasured` |

- **Expected-failure evidence, recorded not fixed**: P1 is expected to score
  poorly on aggregation and superlative. A P1 aggregation EM near zero is a
  **passing** outcome for the project and must not be treated as a defect.
- **Holdout**: no test here reads `acceptance/holdout/`.
- **Unmeasured is a real outcome.**

### Manual

- Run one lookup question (pub-type, e.g. Sailing 2016 RS:X → 26) and one
  aggregation question (pub-001 → 5) through P1 only. Confirm the lookup is
  plausibly correct and the aggregation is wrong. Record both verbatim — this
  pair is the demo's opening move (US-4 and US-5).

---

## Execution Order

1. Wait on **G1** from PLAN-001 (Q5 installed, index `Ready_for_query`) and
   **Group 0** from PLAN-004 (record contract)
2. Group 1 → **verify**: record conformance + citation resolution
3. Group 2 → **verify**: unfiltered assertions pass (**G2**)
4. Final re-analysis pass after the first full batch run: confirm P1's per-qtype
   profile matches the predicted shape (reasonable on lookup, failing on
   aggregation/superlative). If P1 scores *well* on aggregation, something is
   filtered that should not be — investigate before celebrating.

---

## Sub-plan externalization

| Sub-plan | Scope | File | Status |
|---|---|---|---|
| — | none; module is 3 pt | — | — |

---

## Stop conditions

- Any proposal to filter, re-rank, threshold or type-restrict P1's retrieval
  "to improve results" — this is the one module where improvement is the failure
  mode. Escalate rather than implement.
- Any LangChain retriever wrapper appearing in `p1_rag.py`
  (`ContextualCompression`, `MultiQuery`, `Ensemble`, or any reranker). The
  guard test asserts the module imports no retriever class at all.
- `test_p1_unfiltered.py` is edited to make a build pass
- k or chunk size changed after the first scored run in response to that run's
  results
- PLAN-001 G1 not reached by end of day 2 — P1 cannot start and the schedule
  must be re-cut rather than compressed
