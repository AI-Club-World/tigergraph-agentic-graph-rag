# Round 2 — Design: evolving, conflicting and uncertain facts

Status: proposed design, not implemented. Gated items are marked **[GATE Gn]**
and listed in `ROUND2-INTERVIEW-LOG.md`. Assumptions about the unknown Round-2
dataset are marked **[ASSUMPTION]** and must be reconciled when it arrives.

Principles carried over from Round 1:
- Same LLM and same embedding model in all three pipelines, reported.
- Deterministic first; the LLM only where it measurably improves quality.
- No question templates, no qtype read, nothing tuned on the scored set.
- Round-1 records, trace and stop vocabulary stay valid; every new field is optional.

---

## 1. Dataset adapter layer

```
backend/src/ogr/datasets/
  base.py          DatasetAdapter protocol + SourceRecord / ClaimRecord dataclasses
  registry.py      adapter lookup by name; dataset -> adapter mapping
  olympic.py       Round-1 corpus: wraps ingest/infobox.py (unchanged behaviour)
  generic_jsonl.py [ASSUMPTION] text records with optional metadata fields
  injected.py      the Phase-5 injection harness output (section 8)
```

```python
class DatasetAdapter(Protocol):
    name: str
    def documents(self, path) -> Iterable[SourceRecord]: ...
        # doc_id, title, text, url, source_id, source_name, source_class,
        # published_at, valid_from/valid_to (if the record states them), extra: dict
    def claims(self, doc: SourceRecord) -> Iterable[ClaimRecord]: ...
        # structured claims the dataset carries (infobox fields, table cells, KB triples)
    def source_prior(self, doc: SourceRecord) -> float | None: ...
        # reliability prior if the dataset defines one, else None (estimated, §4.3)
```

- Reasoning code (temporal, conflict, uncertainty, agent tools) reads only
  `Claim`, `Source`, `Entity` and `Dataset`. It never reads an adapter or a
  dataset format. A new dataset means a new adapter and nothing else.
- `olympic.py` turns infobox fields into claims (`gold`, `competitors`,
  `nations`, `date`, `venue`) with `observed_at = None`,
  `source_class = "encyclopedia"`, and `extraction_conf = parse_confidence`.
  The Round-1 graph path (`OlympicEvent`, Q1–Q4) is unchanged. The claims are
  an additional view of the same pages.
- **[ASSUMPTION]** `generic_jsonl.py` accepts records with any of `published_at
  | date | timestamp`, `source | publisher | author`, and `text`. This is a
  guess at a common shape, nothing more. The real format replaces it.
- **Text-only claims.** When a dataset gives no structured claims, the claims
  come from prose. Deterministic patterns cover numbers with units, dates and
  hedge cues. An LLM extraction pass at ingest (one-time, cached per chunk
  hash) is optional and gated **[GATE G4]**. The harness must not use an
  extractor written against its own templates (section 8.4).

## 2. Fact model

A **claim** is one statement by one source: *(subject, predicate, value)*
with time, provenance and confidence.

| Field | Meaning | Source of the value |
|---|---|---|
| `subject` (`ABOUT` edge) | Entity, or a Round-1 `OlympicEvent` | Adapter, then entity linking |
| `predicate` | Normalised attribute (`gold`, `competitors`, ...) | Adapter mapping; a closed vocabulary per adapter |
| `value_text`, `value_num` | Stated value; numeric when it parses | Adapter |
| `valid_from`, `valid_to` | When the fact holds in the world | Record field or stated date; open interval when unknown |
| `observed_at` | When the source stated it | `published_at`, else the dataset default, else unknown |
| `source` (`FROM_SOURCE`) | Who stated it | Adapter |
| `extraction_conf` | How sure the parse is (0–1) | Infobox `parse_confidence`, pattern score, or LLM extraction score |
| `hedged`, `hedge_terms` | The statement is qualified ("reportedly", "estimated", "unconfirmed") | Deterministic hedge lexicon, versioned in code |
| `claim_conf` | Confidence in the claim itself, before conflicts are weighed | §4.4 |

Relations:
- `SUPERSEDES(new -> old, reason)`: same subject and predicate; `new` is
  observed later **and** either states that it replaces `old` (correction,
  reallocation, revision) or comes from the same source. Built at ingest,
  deterministic, and the reason is recorded.
- `CONTRADICTS(a <-> b)`: same subject and predicate, overlapping validity,
  values that differ after normalisation, and no supersession between them.
  Built at ingest.

Graph types: `ROUND2-ANALYSIS.md` §5. **[GATE G1]**

## 3. Temporal reasoning

### 3.1 Temporal intent (query time)

`pipelines/temporal.py` `detect_temporal_scope(question) -> TemporalScope`

```
TemporalScope(mode: none|as_of|before|after|between|latest|earliest|original,
              t1: date|None, t2: date|None, cue: str, ambiguous: bool)
```

- Deterministic rules first: the shared date normaliser (`common/dates.py`)
  plus a cue lexicon: "as of", "at the time of", "before", "after", "since",
  "between", "latest", "current(ly)", "now", "most recent", "originally",
  "initially", "first awarded", "later", "after the revision".
  The lexicon is general English, not drawn from eval questions. The
  anti-overfitting tests are extended to scan it.
- The LLM is used only when `ambiguous=True` (a cue with no resolvable date,
  or two conflicting cues), and then only as an optional `temporal` field
  added to the existing intent tool call **[GATE G3]**. Until then,
  ambiguous means "latest", and the trace says so.
- Round-1 questions: `mode=none` for every public question is a regression
  test. A Round-1 question that names an event date must not become a
  time-scoped question; event dates stay entity anchors, as now.

### 3.2 Time-scoped retrieval

- A new query, `q6_claims(subject_ids, predicate, dataset_id, t1, t2, mode)`,
  returns claims with their sources, validity, `observed_at`, confidence,
  and `SUPERSEDES/CONTRADICTS` neighbours, within the scope.
- `as_of t`: claims valid at `t` **and** observed at or before `t` (what was
  known then). `latest`: no filter; supersession decides. `original`: the
  earliest observed claim in each supersession chain.
- Q5 scoped variant `q5s_search(..., dataset_id)` seeds `candidate_set` from
  the dataset's chunks (Round-1 Q5 untouched).

## 4. Conflict resolution and uncertainty

### 4.1 Candidate set

For one (subject, predicate, scope): all claims after the temporal filter.
Superseded claims are dropped from the candidates but kept as evidence.

### 4.2 Score (deterministic, inspectable)

```
score(v) = w_r * mean_reliability(sources of v)
         + w_c * log(1 + independent_sources(v))      # corroboration
         + w_t * recency(v)                            # exp(-age / tau), age vs scope time
         + w_e * mean(extraction_conf of v)
         - w_h * share_hedged(v)
```

- Claims with the same normalised value are merged; "independent" counts
  distinct `source_id`s, so one source repeated is not corroboration.
- **Weights and tau are set on the harness dev split only and frozen before
  the test split is run.** Defaults before fitting: `w_r=1, w_c=0.5, w_t=0.5, w_e=0.3, w_h=0.5, tau=2y`.
- The winner is the argmax. Ties break on later `observed_at`, then on higher
  reliability, then lexicographically, so the result is reproducible.
- Every candidate value, its score terms and its sources go into the trace.
  Losing values become cited conflicting evidence (§6).

### 4.3 Source reliability

- The adapter's prior when the dataset defines one (**[ASSUMPTION]** a
  source class such as official, news, blog).
- Otherwise it is estimated by agreement (a TruthFinder-style fixed point
  over the dataset's claims, at most 10 iterations, deterministic), and
  stored as `Source.reliability_est`.
- No reliability is ever derived from questions or gold answers.

### 4.4 Confidence

- Claim: `claim_conf = extraction_conf * (h if hedged else 1) * reliability`
  (h = 0.6 before calibration).
- Value: `p(v) = softmax(score(v) / T)` over the candidates, so the
  confidence reflects the margin over the runners-up.
- Multi-hop: the confidence of a chained answer is the product of the hop
  confidences. A hop resolved by an exact graph edge (Round-1 Q4 → Q1) has
  confidence `parse_confidence`.
- **Calibration:** `T` (and `h`) are fitted on the dev split by minimising
  negative log-likelihood (temperature scaling). ECE (10 bins) and Brier are
  reported on the test split. A confidence that is not calibrated on held-out
  questions is not reported as calibrated.

### 4.5 Answer policy (decided)

The pipeline always commits to one best answer, gives a confidence, and
cites the conflicting evidence. No abstention by default. Low confidence
(below a threshold fixed on dev) is stated in the explanation, but the answer
is still given.

### 4.6 Where the confidence comes from in the record

Two options **[GATE G2]**:
- (a) **Agent-computed** (recommended). P3 attaches the §4.4 confidence.
  The CORE-02 answer prompt stays byte-identical, so Round-1 is untouched.
  P1 and P2 report no confidence, so calibration is measured for P3 only.
- (b) **Verbalised by the LLM in all three pipelines** (a `confidence` key in
  the answer contract). This compares calibration across pipelines but
  changes the shared prompt, so the Round-1 baseline must be re-run.

## 5. Agent planning (P3)

New loop tools, each counted against the existing budget (`max_steps=6`,
`max_tokens_per_query=20000`) plus `max_corroboration_calls=2`:

| Tool | Graph query | When the planner picks it |
|---|---|---|
| `claims` | `q6_claims` | The anchored subject has claims for the target predicate (and so for every Round-2 dataset) |
| `corroborate` | `q5s_search` restricted to sources not yet seen, then claim extraction | The winner's margin is below threshold, or it rests on one source |
| `resolve` | none (deterministic, §4.2) | After `claims` or `corroborate`: score, pick and attach confidence |

Router: `refine_route` gains one rule. A temporal scope that is not `none`,
or a subject with `CONTRADICTS` edges, routes to the loop with `claims` as
the first tool. Round-1 routing is unchanged when no claims exist and the
scope is `none`; a regression test pins this.

Stop reasons: `sufficient_evidence` when the winner's margin clears the
threshold. A new optional reason, `conflict_resolved`, is added to the closed
vocabulary. Adding to the vocabulary is backward compatible, but the
frontend's label table must be updated.

## 6. Record and trace extensions (all optional, additive)

`PipelineRecord` (new optional fields, `None` in Round-1 runs):
```
confidence: float | None
temporal_scope: {mode, t1, t2, cue} | None
conflicts: [ {subject, predicate, chosen, chosen_score, alternatives: [
              {value, score, sources: [source_id], observed_at, superseded_by}]} ] | None
```

`TraceStep` (new optional field): `details: dict | None` holds score terms,
candidate values and filters. `notes` keeps its one-line human summary.

Round-1 records stay valid as they are, so old `out/` files and the history
view still load. The frontend shows the new fields when present (a
confidence badge, a conflicts table, a time-scope chip).

## 7. Fairness of the comparison

- The same documents go into all three pipelines. Observed time and source
  are written into each chunk's **header text** (`Source: …; Published: …`),
  so RAG sees the same provenance the graph holds. This keeps RAG from being
  weakened artificially.
- Same `k`, same LLM, same embedding model, same answer prompt.
- Relative gain is reported both ways: `(Agentic − RAG)` absolute and
  `(Agentic − RAG) / RAG`, with Wilson 95% intervals, per subset.

## 8. Validation harness (no real dataset yet)

`backend/src/ogr/harness/`: generator-based and parameterised.

### 8.1 What it injects (over the Round-1 corpus)

Seeds are real events and values from the parsed infoboxes. The generator
writes **new documents**; it never edits Round-1 documents.

| Subset | Injection | Ground truth |
|---|---|---|
| evolving | Dated follow-up reports: medal reallocation after a disqualification, corrected participant counts, venue renamed. 1–3 updates per seed, with `published_at` later than the Games. | Value valid at the asked time (as of, latest, original) |
| conflicting | k sources of differing reliability state values for the same attribute. The true value is stated by a configurable share of reliable sources, false values by noisier ones. | The generator's true value (never the policy's choice) |
| uncertain | Hedged statements ("is reported to", "unconfirmed figures suggest"), partial statements (a range, "about 30"), and missing-then-filled values | True value, plus an expected low confidence where the only support is hedged |

Parameters: `seed, n_per_subset, difficulty (number of updates/sources, distractor similarity), conflict_rate, reliable_share, hedge_rate, noise (paraphrase/date-format variety), dev_test_split`.

Domain plausibility: Olympic medals really are reallocated years later after
doping cases, so evolving facts are natural on this corpus.

### 8.2 Questions

Natural-language questions are generated from several phrasings per intent,
with a fixed seed. Records match the Round-1 eval format
(`qid, question, qtype, answer, gold_doc_ids`), with qtype `evolving |
conflicting | uncertain`, so the existing batch runner, scorer and per-qtype
report work unchanged.

### 8.3 Splits

dev (fit weights, T, thresholds) and test (reported once). The generator
seed and parameters are recorded with every run.

### 8.4 Overfitting guard

The harness writes documents in several surface forms (template families
chosen at random, several date formats, synonyms). The claim extractor is
never written against those templates: it uses the adapter's structured
metadata (`published_at`, `source`) and the general hedge and date lexicons.
A test checks that removing any single template family does not change
extractor recall by more than a set margin.

### 8.5 Metrics

Per subset and pipeline: EM, F1, tokens per question (median, mean),
latency; P3 only (unless G2 = b): ECE, Brier, accuracy at the confidence
threshold. Relative gain of Agentic over RAG and over GraphRAG, with Wilson
intervals.

### 8.6 Cost control

A dry run of 10 questions (all three pipelines) before any full run, with a
token estimate for the full run reported before it starts.

### 8.7 Isolation from Round 1

The injected corpus is its own `Dataset`. Round-1 regression runs keep the
Round-1 scope, which depends on G1 (dataset scoping). Without scoping, the
injected documents would leak into Round-1 RAG retrieval, so a harness run
would first have to unload them.

## 9. What this design does not claim

- No measured gain exists yet. Every number in Round 2 comes from a run that
  is recorded in `out/` with its configuration.
- The Round-2 dataset format is unknown; the generic adapter is a placeholder.
- Filtered HNSW recall and schema-change behaviour on Savanna are unverified.
