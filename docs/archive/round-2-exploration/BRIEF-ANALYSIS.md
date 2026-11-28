# Round 2: gap analysis of the real brief against what we have

Branch `round-2`. Written 23 Nov 2026; deadline 29 Nov 2026 23:59 IST (about 6.5 days).
Inputs: `PROBLEM-STATEMENT.md`, `data/README.md`, `data/corpus.jsonl`,
`data/questions_public.jsonl`. The existing round-2 documents (`ANALYSIS`, `DESIGN`,
`PLAN`, `APPLICATION-SPEC`, `ARCHITECTURE-SPEC`, `TECHNICAL-SPEC`, `RESULTS`,
`INTERVIEW-LOG`) are cited, not rewritten.

**Hidden questions.** This analysis deliberately did not open or read
`data/questions_hidden.jsonl`. The brief forbids tuning to it, and the public 50 are
stated to show every style of the hidden 50. Everything about the hidden set below is
inferred from the public set and the brief.

**What is and is not measured.** Nothing in this document was run against TigerGraph or
an LLM; this environment has no credentials (`RESULTS.md`). Corpus and question
statistics were computed from the data files. Everything about our code is read from the
repository, not from a run. Effort sizes (S/M/L) are estimates, not measurements.

---

## 1. What the brief actually scores

| Category | Weight | What it means for us |
|---|---|---|
| Hidden-set accuracy (organisers' key, fact by fact, partial credit; lists must be complete, wrong extras lower the score) | 40% | We need structured, complete answers, not one EM span. Most of the work is here. |
| Honesty (correct `not_in_corpus`, no invented answers) | 10% | We must be able to say `not_in_corpus` and `partial`. An invented answer scores 0. 4 of 50 public are `not_in_corpus`, 2 are `partial`. |
| Evidence (citations that support the answer) | 10% | Citations are `doc_id`s; they must be the supporting ones, not the whole retrieved set. Public `gold_doc_ids` lets us measure this. |
| Repeatability | 15% | One-command `build.sh` / `run.sh`, locked deps, `.env.example`, complete traces written as the code runs, TigerGraph query log whose timestamps match the traces, token sums matching, live reproduction of submitted hidden answers. |
| Efficiency (tokens, latency, cost per question, both sets) | 10% | Must be reported per question and in `metrics.json`; fewer LLM calls and a cheap model help. Scoring scale is not published. |
| Live judging (architecture + demo) | 15% | Judges ask new questions live and read the code for question-specific rules. README must describe ingestion, tools, and how the agent decides. |

Disqualification conditions: answers not reproducible by the system, produced by hand or
by pasting the corpus or questions into a general assistant. Rule 4 (no regexes on
question wording, no qids, no built-in answers) is checked by reading the code.

### Two contradictions with our earlier Round-2 assumptions

1. **Relative gain over RAG is not scored.** `APPLICATION-SPEC.md` (around lines 85-92)
   sets the judged quantity as "relative gain of Agentic GraphRAG over plain RAG" with
   targets of Agentic minus RAG EM >= +0.25 on evolving, conflicting and uncertain
   subsets. Round 2 scores one system's absolute accuracy, plus honesty, evidence,
   efficiency, repeatability and demo. The three-pipeline comparison is not a criterion.
   Those targets should be dropped as goals. The comparison can stay as a demo aid.
2. **"Always commit to one answer, never abstain" now conflicts with the brief.** Our
   recorded answer policy (`INTERVIEW-LOG.md` G2 and the answer-policy decision) was
   written when no abstention was scored. The brief scores `not_in_corpus` and `partial`
   explicitly (10% honesty plus accuracy credit), and an invented answer to an
   unanswerable question scores 0. The policy must change (decision D1).

Smaller mismatches: our contract is a single span `{answer, explanation}` with EM/F1
scoring; the brief wants lists and JSON scored fact by fact. Our Round-1 record and trace
format differs from the required one (section 4, gap G1).

---

## 2. Data profile

All figures computed from the data files unless marked otherwise.

**Corpus: 3,530 documents** = the 2,951 Round-1 documents, unchanged, plus 579 new:

| New group | Docs | Real/fictional | Notes |
|---|---|---|---|
| Paris 2024 event articles | 299 | real | Wikipedia |
| Milano Cortina 2026 event articles | 114 | real | Wikipedia |
| LA 2028 event articles | 127 | fictional (`synthetic: true`; `url`, `wikidata_qid`, `wikipedia_pageid` null) | key on `doc_id` |
| LA 2028 source records | 39 (`SYN-LA28-S001`..`S039`) | fictional | see below |

(166 documents carry `synthetic: true` in total: 127 + 39.)

**Round-1 infobox parser on the new corpus** (our existing parser, run offline): 2,727
Olympic events parsed; 0 missing sport, 0 missing Games, 0 duplicate event ids; 28
low-confidence. Of the 540 new events, 539 have a gold medallist, 453 have nations, 535
have a gold NOC. Games now include 2024-Summer (299 events), 2026-Winter (114) and
2028-Summer (127). So the existing Olympic ingest largely carries over to the new event
articles, including the fictional ones. Not yet checked: whether the LA 2028 articles
carry the extra prose the "why" and dispute questions need beyond the infobox (they do
in at least 020, 021 per the gold documents).

**Other infobox types in the corpus:** olympic event 2,727; film 546; officeholder 73;
person 65; none 56; company 16; others small. Film infobox keys include `director`,
`released`, `starring`, `budget` (496 docs), `gross` (517). Officeholder keys include
numbered fields (`office1/2`, `predecessor1/2`, `successor1/2`, `term_start*`).
Public question 019's note says the infobox lists the Senate predecessor first and the
governorship second. Our Round-1 graph turns only Olympic-event infoboxes into graph
data; film, officeholder and person pages exist only as Document + chunks.

**Prose results tables:** 964 documents contain "Rank |" tables in prose (217 of them new).

**The 39 source records.** Short prose. Each opens with a synthetic notice, then
`Source: <who>` and `Published: <ISO local time, PDT>`, then free prose. There is **no
key/value block**, so the speculative `datasets/block_records.py` adapter (which assumed
`[Infobox ...]` key:value blocks with published_at and source fields) does not match.
Claims must be extracted from prose. Source authority spans four visible classes:

| Class | Examples seen in the records |
|---|---|
| Official | signed jury decisions, certificates, registers, signed assignments, binding bulletins, race-director signed log |
| Operational (may be provisional) | scoreboard operator, timing data, registration systems, published schedules |
| Secondary | news, newsletters, bulletins, headline sites |
| Unreliable | blogs, fan posts, voice notes, volunteer notebooks, tourism sites, ticket emails, medal aggregator, legacy feed |

Worked examples from the files: S011 (scoreboard capture, published 2028-07-23 21:09,
header "PROVISIONAL RESULTS", bronze = Bouchardy); S031 (photo-finish jury, signed,
published 22:15, official and "takes effect at 22:15 PDT on 23 July 2028", bronze =
Asante-Mensah); S016 (spectator blog, 24 July) repeats the provisional order; S037 venue
planning draft v0.7 (15 June) versus S030 signed assignment final v1.0 (1 July); S005
tourism site (27 July) repeats the draft. Each claim therefore has three times: event
time, publication time, and effective time (cf. public 040). **Publication recency must
not decide.** A later secondary source repeating older data must not win (041, 043).

Our resolver (`reasoning/resolve.py`) has a recency term (its fitted weight came out 0
on the synthetic harness) and a rule that a dated revision supersedes an undated
statement. Both could misfire here, because a later blog is dated and the official
decision may carry only an effective time in prose.

**Public questions (50):** status `answered` 44, `not_in_corpus` 4 (028, 031, 046, 049),
`partial` 2 (029, 048). Answers are strings, JSON objects or lists. Each has
`gold_doc_ids` (0 to 16 documents) and sometimes a note.

---

## 3. Question-style capability matrix

The brief says the public 50 show every style in the hidden 50. A style that is absent or
weak in our system therefore costs us a proportional share of hidden questions. The
styles below are my grouping of the public questions by what they need; they are not
labels from the brief. The hidden count per style is unknown; the public count is the
best proxy.

| Style | Public qids | n | Capability needed | What we have | Gap |
|---|---|---|---|---|---|
| Repeat winners across Games | 001, 002, 032 | 3 | Athlete x same event x multiple years; group gold medallists across editions | Event vertices with gold names as attributes; no athlete entity; Q3/Q2 are per-event | Athlete index plus cross-edition grouping; list-valued output |
| Filtered list / count-compare in one sport and Games | 003, 006, 007, 008, 033 | 5 | Golds by NOC per sport/Games; list events a nation won; count distinct gold nations | Q2 count with constraints; Q3 argmax top-3 | No group-by-NOC; no "list all matching"; no distinct count; list completeness |
| Same event across named years | 004, 029, 036; 037 (NEXT edition) | 4 | Lookup per year including 2028; partial coverage; "held immediately after" | Q1 lookup; Q4 traverse with NEXT_EDITION in the graph, unused by any agent route | Multi-year fan-out; routing NEXT/PREV; partial status when a year is missing (029: 2008) |
| Films | 005, 017, 030, 031 | 4 | Director filter plus release year; gross < 2x budget (money parsing); indirect evidence (030: director known only from another article); not_in_corpus (031) | Film pages are Document + chunks only | Film infobox into graph; money parsing; document-scoped prose retrieval; absence detection |
| Politicians | 018, 019 | 2 | Predecessor/successor chains with numbered offices | Document + chunks only | Officeholder infobox with numbered offices; chain traversal |
| Trends across Games with max/min | 009-012 | 4 | Nations per edition for one event; highest and lowest | Q2 can count one event; no per-edition series | New aggregation returning a series plus extremes |
| Athlete careers | 013-016, 034 | 5 | All medals of a person across event docs (incl. 2028 fictional 034); sometimes individual-only filter (016) | No athlete entity | Athlete index; medal-type attributes |
| Why (article text only) | 020-024 | 5 | Document-scoped prose retrieval, short explanatory answer | Q5 hybrid search over chunks, rerank | Scope retrieval to the right event doc; answer from prose, not infobox |
| Superlative within sport and Games, most and fewest | 025-027, 035 | 4 | Scan all events of a sport at one Games; argmax and argmin | Q3 ranks DESC only | argmin; "fewest" |
| Simple lookup | 038 | 1 | One field | Q1 | none expected |
| not_in_corpus | 028, 031, 046, 049 | 4 | Detect that the needed document or fact does not exist, not just a low retrieval score | Evidence check, ask-back on ambiguity (not abstention) | Coverage/absence detection; status output |
| partial | 029, 048 | 2 | Answer what is supported, state what is missing; return rival unverified claims | None | Status decision; claim-level answers |
| Source-record reasoning | 039-050 | 12 (24%) | Provisional vs official, effective time, draft vs final, as-of cutoff, registrations vs starters, absence of evidence vs evidence of absence | Claims layer designed and coded (not installed); resolver with recency | Prose claim extraction; authority-first resolver; effective-time field; as-of scoping |

Counts overlap (029 is both same-event and partial; 031 is both film and
not_in_corpus), so the column does not sum to 50. The source-record block alone is 24% of
the public set, and probably about the same share of the hidden one.

---

## 4. Gap list, ranked by expected score impact

Ordering follows the weights: accuracy (40) > repeatability (15) = live (15) > honesty,
evidence, efficiency (10 each). Because a failure to produce a valid submission zeroes
everything else, G1 is first despite being mostly plumbing.

"Gate" means a change to the TigerGraph schema, ingest or the LLM setup that the owner
must approve (the existing gates, G4 allows LLM extraction at ingest).

| # | Gap | Effort | Risk | Gate | Main score lines |
|---|---|---|---|---|---|
| G1 | Submission contract and scripts | M | Low | LLM key and TG access only for running | Repeatability, all |
| G2 | Status decision and absence detection | M | Medium: over-abstaining costs accuracy | No | Honesty, accuracy |
| G3 | Structured answers and fact-level scorer | M | Low | No | Accuracy (and our ability to measure it) |
| G4 | Athlete index | M | Medium | **Schema** | Accuracy (about 8 public: 001, 002, 013-016, 032, 034) |
| G5 | New aggregations (group-by NOC, list filter, argmin, trend, NEXT) | M | Low-medium | New installed queries (**schema/queries**) | Accuracy (about 17 public) |
| G6 | Prose claim extraction for source records, authority-first resolver | L | High: the least-tested part | **LLM setup** (extraction), new claim schema | Accuracy (12 public), live demo |
| G7 | Generic infobox claims for film, officeholder, person | M | Medium | **Schema** | Accuracy (6 public) |
| G8 | Document-scoped prose retrieval for "why" and indirect evidence | S-M | Low | No | Accuracy (about 6 public) |
| G9 | Multi-step planner | L | High | LLM prompts | Accuracy, live |
| G10 | Citations precision | S | Low | No | Evidence |
| G11 | Efficiency reporting and model choice | S | Low | LLM choice (**decision D5**) | Efficiency |
| G12 | Repeatability hardening (temperature, determinism, tag, logs) | S | Low | No | Repeatability |

### G1. Output, trace and metrics contract, scripts, logs, counts, locked deps (first)

Missing, from the repository listing and reading:
- No `build.sh` or `run.sh` at the repo root (only `Makefile`, `run.bat`). Needs
  `./build.sh corpus.jsonl` (schema install, load, embeddings, query install) and
  `./run.sh <questions> <answers>`, both idempotent.
- Per-question record in the required shape: `qid, status, answer, explanation,
  citations, input_tokens, output_tokens, latency_ms, trace[]`. Our Round-1 record and
  trace differ. Trace steps must be written by the code as it runs, with `step`, `tool`,
  `tigergraph`, and for TigerGraph steps `query`, `params`, `rows`; LLM steps carry
  tokens; every step has `ms`.
- Invariants the organisers will recompute: LLM step tokens sum to the totals; step times
  roughly sum to `latency_ms`; every TigerGraph step appears in the query log.
  Enforce with a self-check in `run.sh` that fails loudly.
- `metrics.json` for both sets in the format of `data/README.md`
  (`accuracy_pct` null for hidden, `accuracy_method` text, p50/p95, calls per question,
  `answers_with_tigergraph_step`, `cost_usd_total`, run time). Compute only from the
  answer files.
- TigerGraph query log with timestamps matching traces: a client-side request log with
  timestamps (written at call time, in the same clock as the trace) is the safest
  option; the server RESTPP log may not be reachable on a managed workspace (open
  question O3).
- Graph counts by vertex and edge type after loading, as a file produced by `build.sh`.
- Locked dependencies: `backend/pyproject.toml` exists; no Python lock file was found in
  the repo listing (`backend/package-lock.json` / root `package-lock.json` look like the
  frontend). Needs a lock or exact pins. `env.example` exists but is `env.example`, not
  `.env.example`, and lists keys for UI-selectable providers; trim and rename.
- Both runs must use the same code and settings; the tag is created at the deadline.
- Answers must not depend on the browser UI.

### G2. Status decision and coverage/absence detection

The agent must output `answered | partial | not_in_corpus`. The public set tests four
different absence patterns, which need different mechanisms:

| qid | Why nothing is answerable | Detection |
|---|---|---|
| 028 | No LA 2028 doc exists for that event, although 127 others do | Structured lookup finds no event vertex for the (event, Games) pair |
| 031 | A film is mentioned in other articles, never with box-office figures | Film claim lookup finds no `gross`; prose search finds no supporting passage |
| 046 | Only anonymous reserve slots R1, R2; no identities | Claim extraction must record "anonymous", not invent names |
| 049 | No official duration; even occurrence unconfirmed | Resolver: only unreliable sources, no official claim, so no verified value |

We have an evidence check and ask-back on ambiguity, but ask-back is not abstention.
Design point: the status should come from the structured result (empty set, missing
field, only low-authority claims) before the LLM writes the answer, with the LLM only
phrasing it. Our Platt-calibrated confidence can feed this decision (section 5). Risk:
thresholds tuned on 4 `not_in_corpus` and 2 `partial` examples will overfit; keep rules
generic (empty result, missing attribute, no authoritative claim) and check on the
check split (D7). No measurement exists for how often our current agent returns a
confident wrong answer where the key says `not_in_corpus`.

### G3. Structured answers and fact-level scorer

Answers are lists of records and JSON objects (001, 003, 005, 009-016, 029, 045, 048).
Needed:
- An answer contract where `answer` can be text or JSON (list of records), complete, no
  truncation to top-3.
- A public self-scorer approximating the organisers' fact-by-fact partial credit:
  flatten the gold and predicted answers to a set of (key, value) facts, then compute
  recall of gold facts and a penalty for extra wrong ones. The organisers' exact rule is
  unknown (O1); ours is an approximation and `accuracy_method` must say so. Our EM/F1
  scorer cannot score lists.
- Output-format stability: judges check against a key, so field names will not match
  exactly; keep answers readable and include the key facts in the `explanation` as well
  as in `answer`.

### G4. Athlete index (schema gate)

Questions 001, 002, 013-016, 032, 034 need "all medals of a person" and "same event won
at more than one Games". Options:
- (a) A `Person`/`Athlete` vertex with `WON_MEDAL` edges (medal, event, year) built at
  ingest from the infobox/medal tables. Fast at query time, clean in the demo, needs
  name normalisation and a schema change.
- (b) A GSQL scan over the medallist list attributes of event vertices at query time.
  No schema change, but string matching on names inside list attributes; the
  cross-edition grouping is awkward in GSQL.
Recommendation: (a), reusing the claims layer's Entity vertex if D3 is accepted.
Risks: name variants (diacritics: "Aurélien", "Novaković", and Wikipedia name forms),
individual versus team events (016 asks for individual titles only), and events where
the same athlete appears for different NOCs. The medal tables in the 964 prose "Rank |"
documents may be needed for silver and bronze; whether the infobox alone gives all three
medals for every event was not checked.

### G5. New aggregations

Needed operations beyond Q1-Q4, all over the event vertices: gold count by NOC for
(sport, Games); list events where NOC = X and medal = gold; distinct gold NOCs;
argmax and argmin of nations or athletes for (sport, Games); series of nations per
edition for one event with max and min; NEXT/PREV edition. Q3 ranks DESC and top-3
only. Note 038 (athlete count, decathlon) and 025-027, 035 depend on a numeric field
being present and parsed; 28 events were low-confidence in our parser and 87 of the 540
new events lack nations, so some answers will be partial or absent. These are new
installed GSQL queries and need an install gate. Prefer one or two generic, parameterised
queries (filter, group-by, order, limit) over one query per question style, so the
planner composes them and no question wording is baked in.

### G6. Source records: prose claim extraction, authority-first resolution

The largest and highest-risk gap: 12 public questions (24%) and the centre of the live
demo. Needed:
- LLM extraction at ingest over the 39 records and 127 LA 2028 event articles, giving
  claims `(subject, attribute, value, source, authority class, published_at,
  effective_at, event_time, doc_id, status marker such as provisional/draft/final)`.
  Gate G4 allows this; cost is small (about 166 documents).
- Authority class: derive from the `Source:` line by a small generic mapping learned in
  the prompt (official / operational / secondary / unreliable) rather than a list of
  names in code, so it works on new sources the judges may use. Hard-coding the 39
  sources would be a built-in answer.
- Resolver change: authority first, then effective time; recency only as a tie-break
  within the same class, and never allowed to let a later secondary source repeating an
  older value win (041, 043, 016, 005). Remove or demote the rule "a dated revision
  supersedes an undated statement" and the recency weight.
- As-of scoping: "as of July 2, 2028" returns the latest claim effective at or before
  the cutoff (044); "provisional record as of 21:09" returns the claim of that time (039).
- Explanation content: which value, why, what differed and why (047), what was never
  confirmed (048-050).
- Registered versus competed (045) is an attribute-level distinction, not a source
  conflict; claim attributes must keep the two apart.
- Install the claims schema (`schema_round2.gsql`, Q6, Q5S), written but never installed
  on TigerGraph and whose reinstall behaviour on the target workspace is unverified
  (`INTERVIEW-LOG.md` G1).
Risk: extraction errors cascade into wrong answers; mitigation is to keep the source
text span with each claim and let the answering step quote it. The resolver cannot be
validated beyond the public 12, so there is a real overfitting risk (D7).

### G7. Generic infobox claims for film, officeholder, person (schema gate)

Questions 005, 017, 018, 019, 030, 031. Needed: ingest of the non-Olympic infobox types as
entities with typed attributes, parsed money (`budget`, `gross`: units, ranges,
citations like "$100 million [1]", currency) for 017, numbered offices
(`predecessor1`, `predecessor2`...) paired with the matching `office1`, `office2` for
018/019 (note says the Senate predecessor is listed first), and dates (`released`).
Alternative with no schema change: leave them as chunks and let the agent read the
infobox text through document-scoped retrieval (G8). That is cheaper and may do for
single-document questions (017 needs a scan of Spielberg films: 5 gold docs, so a
structured filter is more reliable). Recommend structured for film and officeholder,
prose fallback for person. Not measured: how many of the 546 film pages parse
cleanly; 496 have `budget` and 517 `gross` keys, so these are present but unparsed.

### G8. Document-scoped prose retrieval

"Why" (020-024) and indirect evidence (030) have one gold document each. Our Q5/Q5S are
hybrid search over all chunks. Needed: identify the target document first (by entity /
event / title through the graph), then retrieve and answer within that document. 030
(who directed Cocoon) is answerable only from another article, so retrieval must not be
restricted to the Cocoon page; this is a case for a general "find mentions of entity X"
tool rather than a title match. Effort is small because Q5S exists.

### G9. A planner that can chain tools

The Round-1 agent has a deterministic router over a four-operation intent schema
(LOOKUP / COUNT / ARGMAX / TRAVERSE). Round-2 questions need two to five steps
(for example 042: planned venue from draft, actual from signed assignment and event
record; 040: official claim plus effective time; 001: gather medallists, group, filter).
Options: (a) extend the intent schema with the new operations (G5) and keep the
deterministic router: predictable, cheap, hard to write without question-specific rules;
(b) LLM planner that picks from tool descriptions and chains calls, bounded to a few
steps, with the deterministic status checks (G2) after it. The brief says "plans its
own steps" and judges ask new questions, so a tool-calling planner is closer to what
they will test, but it costs tokens and adds nondeterminism. Recommendation: (b) with a
small tool set, temperature 0, step cap, and the Round-1 intent router kept as a fast
path for single-lookup questions. The live demo of a new question depends on this more
than on any other single gap. Rule 4 constrains the router: no regexes on wording.

### G10. Citations precision

Evidence is 10% and requires supporting `doc_id`s. Public `gold_doc_ids` lets us measure
precision and recall. Cite the documents the answer actually rests on: for a source
conflict, the winning official record and, where the explanation mentions it, the
overridden one; for aggregates over many events (006: 18 events), the brief's own example
cites all event documents involved. Do not cite everything retrieved. Whether the key
rewards citing the losing sources is unknown (O2).

### G11. Efficiency

Reported per question and in `metrics.json`. Levers: structured tools do the counting,
the LLM only plans and phrases; skip the LLM answer step when the structured answer is
already complete (risky for explanations); cache nothing across questions in a way the
traces would hide. The model choice (D5) dominates cost. Scoring scale is not published,
so treat as a tie-breaker behind accuracy.

### G12. Repeatability hardening

Temperature 0, fixed seeds where available, deterministic ordering of results in tool
output, same settings for both runs, no hidden state between questions, `run.sh` safe to
re-run, git tag at the deadline, README accurate. Judges will re-run a few hidden
questions: LLM nondeterminism means the answer may differ in wording; keep the facts
stable by having structured tools produce the facts and the LLM only phrase them.

---

## 5. Keep, change or drop from the speculative Round-2 work

| Item | Verdict | Reason |
|---|---|---|
| Claims fact layer (Dataset/Source/Entity/Claim, SUPERSEDES/CONTRADICTS), `schema_round2.gsql`, Q6, Q5S | **Keep, repurpose** | It is what 12 public questions need; claims come from prose extraction instead of block records. Extend Entity to Athlete/Person (D3). Not yet installed. |
| `datasets/block_records.py` adapter | **Replace** | Assumes key:value blocks; the real records are prose with a `Source:`/`Published:` header. Replace with an LLM prose extractor producing the same claim rows. The header parse itself (source, published time) can be deterministic. |
| Temporal scope detector | **Keep, check** | Needed for 039/044 ("as of"). Review it against the new wording ("provisional... before the photo-finish review", "as of July 2"). Verify it does not rely on question-wording regexes in a way that violates rule 4. Not measured on real questions. |
| Conflict resolver | **Change** | Authority first, then effective time; recency only as tie-break; remove "dated revision beats undated". Reliability and corroboration terms may stay but corroboration needs care: a blog copying the scoreboard is not independent evidence (041). |
| Calibrated confidence (Platt) | **Keep, feed status** | Use it as one input to answered/partial/not_in_corpus. Calibrated on the synthetic harness only; recalibrate on the public 50 or do not claim calibration. |
| Synthetic harness (`harness/`) | **Demote** | The real public 50 is the dev set. Keep for unit-level regression of the resolver only. |
| RAG / GraphRAG pipelines | **Keep for demo only** | Not scored. Useful in the live call to show why the graph helps. Do not spend build time on them; `run.sh` runs the agent only. |
| Round-1 Q1-Q5, rerank, evidence check, verification | **Keep** | Basis of the baseline run (plan day 1). |
| Round-1 EM/F1 scorer | **Extend** | Add the list/JSON fact scorer (G3). |
| Frontend / API | **Out of scope** | Not required by the brief; judges screen-share. Only touch if needed for the demo. |
| APPLICATION-SPEC relative-gain targets | **Drop** | Contradiction 1. |

---

## 6. Decisions needed from the owner

**D1. Answer policy.**
- Options: (a) keep "always commit"; (b) allow `partial` and `not_in_corpus`, driven by
  structured evidence; (c) abstain liberally.
- Recommendation: (b). The brief scores both statuses and 10% honesty, and an invented
  answer scores 0; (a) gives up 4 of 50 public questions outright plus the honesty
  weight.
- Consequence: supersedes the INTERVIEW-LOG answer policy; the `{answer, explanation}`
  contract and the Round-1 prompt need a status field. Risk of over-abstention lowering
  accuracy, controlled by keeping abstention rules generic and testing on the check split.

**D2. Does the three-pipeline comparison stay?**
- Options: (a) drop; (b) keep as demo-only, not in `run.sh`; (c) keep as a headline.
- Recommendation: (b). The brief scores one system.
- Consequence: less maintenance; the demo can still show RAG failing on a conflict
  question if time allows.

**D3. Schema additions.**
- Options: (a) none, scan lists in GSQL and read infoboxes from chunks; (b) Athlete/Person
  entity and medal edges only; (c) (b) plus generic Entity claims for all infobox types
  (film, officeholder, person) and the prose claims.
- Recommendation: (c), reusing the Entity/Claim schema already coded. It serves G4, G6, G7
  with one install and gives the demo a clear story.
- Consequence: one schema change on the live workspace (reinstall of queries
  unverified on the target, as `INTERVIEW-LOG.md` G1 notes) and a backfill; about 1
  day of the plan.

**D4. LLM extraction of claims from prose at ingest.**
- Already allowed under G4; needs confirmation for the 39 records and the 127 LA 2028
  articles.
- Options: (a) LLM extraction for the 166 synthetic docs only; (b) also for film and
  officeholder pages (deterministic parsing is preferable there); (c) no LLM, regex.
- Recommendation: (a), deterministic infobox parsing for the rest. Regex on source
  prose risks rule-4 findings and brittleness on new records; the corpus is fixed so
  cost is small and `build.sh` stays one command. Extraction output should be cached in
  a committed file so `build.sh` is reproducible, with the cache key being document
  text and model.

**D5. Which LLM and model for the run.**
- Efficiency (10%) counts tokens, latency and cost on both sets; accuracy counts 40%.
- Options: one capable model for everything; a cheap model for planning and a stronger
  one for answering; a cheap model throughout.
- Recommendation: decide after the day-1 baseline measures tokens per question with the
  current default; do not choose by assumption. The brief's example shows 2-3 LLM calls
  per question as normal.
- Consequence: cost and token numbers can only be known live (D6).

**D6. Credentials timing.**
- Nothing about accuracy, tokens, latency or the query log can be measured without TG
  and LLM access. All current Round-2 numbers are offline component results.
- Recommendation: obtain TigerGraph and LLM credentials immediately; day-1 work depends
  on them.
- Consequence: without them by day 2 the plan below shrinks to offline development and
  a single late live run, which is a high repeatability risk.

**D7. Dev set versus held-out check.**
- The public 50 are the only labelled data and are also the only guide to the hidden
  styles. Tuning every rule to them risks overfitting that the live judging (new
  questions) will expose.
- Proposal: split the public 50 by style into dev and check (for example, hold out
  about one question per style: 003 or 033, 010, 012, 015, 017, 020, 026, 035, 042 or
  043, 047, 049), freeze the check set until the end, and report both in
  `accuracy_method`. Also write 10-15 new questions of our own per style as a smoke test
  (not in the repo as answers built into code).
- Consequence: fewer dev examples for the weakest styles (source records have only 12
  items), so the hold-out for that style must be small. Final accuracy on public is
  reported on all 50 as the brief requires.

---

## 7. Six-day plan

Days are working days from 23 Nov. "Offline" means doable without credentials.

| Day | Work | Needs credentials? | Result |
|---|---|---|---|
| 1 (23-24 Nov) | Get credentials (D6). G1: write `build.sh`, `run.sh`, answer-record and trace writers, `metrics.json` builder, self-checks (token sums, step times), query-log writer, graph counts script, lock file, `.env.example`. Load the 3,530-document corpus on TigerGraph using the Round-1 pipeline. Baseline run of the current agent on the public 50 with the new contract. Record baseline accuracy with the existing scorer and tokens per question. | Mostly yes; the scripts and contract can be built offline first | A submittable (if weak) `answers_public.jsonl` and `answers_hidden.jsonl` exist early |
| 2 | G3 fact-level scorer (offline). G2 status decision from structured results. G5 generic aggregation queries (filter, group-by, argmax/argmin, per-edition series, NEXT) written offline, installed and tested live. Decide D3, D4 before this day. | Install and test: yes | Lists, counts, trends, superlatives (about 17 public questions) |
| 3 | G4 athlete index (schema install and backfill); G7 film and officeholder ingest, money parsing, numbered offices. | Yes | Careers, repeat winners, films, politicians |
| 4 | G6 prose claim extraction (prompt, cache, load), resolver rewrite (authority first, effective time, as-of), claims schema install, Q6 queries. Offline: resolver unit tests on the 12 public cases' claims written by hand from the corpus as test fixtures (not in code). | Extraction and install: yes | Source-record questions (12 public) |
| 5 | G9 planner with chained tools and step cap; G8 document-scoped retrieval; G10 citations; second full public run; error analysis by style on dev only; fix generic causes. | Yes | First full integrated run; check split unfrozen once |
| 6 (28 Nov) | Freeze code. Full clean `build.sh` from scratch, both `run.sh` runs, verify invariants, `metrics.json`, query log, graph counts, README architecture section, git tag at the deadline. Rehearse the live demo with 5-10 new questions and 2-3 reproduced hidden answers. | Yes | Submission package |
| 7 (29 Nov, until 23:59 IST) | Buffer only: re-run, tag, submit. | Yes | |

Offline-capable throughout: the contract writers, scorer, resolver changes, prompt
drafting, unit tests, README. Needs credentials: anything that measures accuracy,
tokens, latency, cost, or installs on TigerGraph. If credentials slip, the first thing
to cut is G9 (keep the router with extended operations) and the person/film
generalisation of G7.

Suggested cut order if time runs out (lowest score per effort first): G9 LLM planner,
G11 tuning, G7 person pages, G4 in favour of a GSQL scan, then G6 sophistication (keep
the authority-first rule, drop corroboration).

---

## 8. Open questions for the organisers

Only items the brief does not settle:

1. **O1.** How is "fact by fact" partial credit computed for list and JSON answers: are
   field names matched, or is the answer judged semantically? Does answer format
   (text versus JSON) matter?
2. **O2.** For source-conflict questions, do citations need to include the overridden or
   unreliable documents named in the explanation, or only the authoritative ones?
3. **O3.** What counts as an acceptable TigerGraph query log on a managed workspace where
   the RESTPP log may not be accessible: is a client-side log with timestamps enough?
4. **O4.** For `partial` answers, is `answer` expected to contain only the supported
   part, with the missing part in `explanation`, or a structure like the public 029
   (`found` plus what is missing)? The public examples show different shapes (029, 048).
5. **O5.** Is the LLM allowed to be called at ingest for claim extraction, and must the
   extraction be re-runnable inside `build.sh` (versus a committed cache)?
6. **O6.** For efficiency, is there a reference model or token budget the score is
   normalised against?

(O5 overlaps with our own gate G4; it is listed because the live judges may probe it.)
