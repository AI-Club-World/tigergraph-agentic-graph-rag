# BUILD-PLAN.md
Agentic GraphRAG Hackathon — Single Task Split (replaces MODULE-BREAKDOWN.md + DELIVERY-STREAMS.md)

**Repository**: https://github.com/AI-Club-World/tigergraph-agentic-graph-rag
Status: **T1 scope, all decisions locked to recommended options (2026-09-21)**
Round-1 target **Wed 24 Sep 2026** · **62 pt** across 2 modules (backend 47 · frontend 9 · shared/docs 6)
Effort scale: **S = 1 pt** (~half-day), **M = 2 pt**, **L = 3 pt**

---

## 0. The core task

> Build three pipelines — **RAG**, **GraphRAG**, **Agentic GraphRAG** — that
> answer the **same questions** over the **same corpus** (2,951 documents) and
> the **100 evaluation questions**, then benchmark them to determine **when a
> multi-step agentic investigation beats simpler retrieval, and when it is
> overkill** once token and complexity cost are counted.

Everything below exists to produce that comparison and make it checkable. The
dashboard is where the answer is read: an aggregate benchmark view plus a
**per-question table covering all 100 eval questions across all three
pipelines**, with the 50 hidden-question outputs rendered by the same component.

---

## 1. Fixed platform decisions

| Layer | Choice | Note |
|---|---|---|
| Repository | `AI-Club-World/tigergraph-agentic-graph-rag` | Single repo, two modules |
| Backend module | `backend/` — Python 3.11 · FastAPI · `sse-starlette` · `uv` + lockfile | |
| Frontend module | `frontend/` — React + Vite · native `EventSource` | |
| Orchestration (P3) | **LangGraph** `StateGraph`; LangChain for provider abstraction, function-calling, usage callbacks | No `GraphCypherQAChain`, no text-to-GSQL |
| LLM | **Pluggable** — native Claude or Gemini clients, or any OpenAI-compatible endpoint (local Ollama/llama.cpp/vLLM via `base_url`, or a free-tier cloud), selected by `LLM_PROVIDER` | One boundary (`common/llm.py`); pinned within a run, swappable between runs |
| Graph + vector store | **TigerGraph Savanna — mandatory for both vectors and graph** | No FAISS, Chroma, pgvector or any external index anywhere. Hackathon eligibility condition. Only permitted fallback is local Community Edition 4.2+ |
| Embeddings | BAAI/bge-small-en-v1.5, 384-dim, local, `sentence-transformers` | Vectors are **stored in TigerGraph**; only the encoder is local |
| API security | `X-API-Key` header from configuration on every route except `/health`; SSE streams use a short-lived single-use `?token=` | See §3 |

### Repository layout

```
tigergraph-agentic-graph-rag/
├── backend/
│   ├── src/ogr/{common,ingest,graph,pipelines,eval,api}/
│   ├── tests/
│   ├── pyproject.toml + uv.lock
│   └── .env.example
├── frontend/
│   ├── src/{components,views}/
│   └── package.json
├── acceptance/
│   ├── holdout/eval_hidden.jsonl      # batch runner only — never opened by a person or assistant
│   └── paraphrase/paraphrase_set.jsonl
├── data/            corpus.jsonl, eval_public.jsonl
├── out/             run JSONL, dashboard output
├── .github/workflows/ci.yml
├── Makefile · README.md · ARCHITECTURE.md · ATTRIBUTION.md
```

---

## 2. Branching model for parallel assistants

`main` is protected and always green. **One short-lived branch per task ID**,
one pull request, squash-merged.

| Rule | Detail |
|---|---|
| Branch name | `feat/<TASK-ID>-<slug>` — e.g. `feat/GRAPH-02-infobox-parser`, `feat/WEB-01-three-column` |
| Scope | One task ID per branch. A branch touching two task IDs is split before review |
| Lifetime | Under one working day. Rebase on `main` before opening the PR |
| Merge order | Contract branches first: `feat/CORE-01-record-contract` merges before any producer branch is opened |
| CI required to merge | backend `pytest` green · `ruff` clean · frontend `npm run build` + tests green · **holdout grep** passes · **no-test-modified** check passes |
| Ownership boundary | Each module's directory has one owning plan; a branch that edits another module's files needs the owning plan updated in the same PR |

**Two CI checks exist specifically because assistants write the code:**

1. **Holdout grep** — fails if any file outside `backend/src/ogr/eval/batch_runner.py`
   references `acceptance/holdout/`.
2. **No-test-modified** — fails if a PR modifies a file under `backend/tests/`
   *and* source in the same commit, unless the commit message carries
   `TEST-CHANGE:` with a reason. This is the failure that silently invalidates
   every benchmark number, and it leaves no other trace.

Conflict-prone shared files — `common/models.py`, `common/dates.py`,
`eval/scorer.py` — are written once, early, on their own branch, and are
edit-by-exception afterwards.

---

## 3. API security

Mandated: backend APIs protected by an API key held in configuration.

- `OGR_API_KEY` in `.env` (never committed; `.env.example` carries the shape).
- FastAPI dependency applied at the **router** level, so a newly added endpoint
  is protected by default rather than by someone remembering.
- `/health` is the only unauthenticated route.
- **`EventSource` cannot send custom headers**, so the two SSE endpoints are not
  header-authenticated. `POST /query` and `POST /build` return
  `{id, stream_token}`; `GET …/stream?token=` accepts a single-use token scoped
  to that id and expiring in minutes. The long-lived key never enters a URL,
  browser history or an access log.
- The frontend reads its key from runtime config. A key delivered to a browser
  is not a secret against a determined attacker — it is protection against
  casual access on a shared network, which is the actual threat here. Default
  binding stays `127.0.0.1`; `--host 0.0.0.0` must be explicit.

---

## 4. Gates

| Gate | Trigger | Verification |
|---|---|---|
| **G0** — Vector proven + contract frozen | SPIKE-01, GRAPH-01, CORE-01 | `vectorSearch()` returns on a 20-doc toy schema **in TigerGraph**; schema installs twice cleanly; both eval files parse into `Question` |
| **G1** — Corpus queryable | GRAPH-02…07, GRAPH-09 | All 5 queries callable; `/restpp/vector/status` = `Ready_for_query`; pub-001 replicates through GSQL (**= 5**) |
| **G2** — P1 + P2 answer | RAG-01, GRAPH-08 | Both conform to `PipelineRecord`; one question per qtype |
| **G3** — Scoring + API proven | EVAL-01, EVAL-02, API-01 | Scorer reproduces hand-computed EM/F1 on pub-001, pub-014, pub-067; API rejects a request with no key and accepts one with it |
| **G4** — P3 answers | AGENT-01…07 | One question per operation traced by hand; **LOOKUP traverses zero loop edges** |
| **G5** — Full run + UI live | WEB-01…04, EVAL-04 | 3 columns populate at visibly different times; **100 × 3 run complete, zero silent failures**; eval table shows all 100 questions across all 3 pipelines |
| **G6** — Submission | HID-01, REPRO-01, DOC-01…04 | `make reproduce` on a clean clone; 50 hidden outputs written; diagram, README, video |

---

## 5. Task table

| ID | Module | Task | Depends on | Eff | Gate | Branch |
|---|---|---|---|---|---|---|
| REPO-01 | both | **Repo scaffold + CI from day 0**: `backend/`+`frontend/` skeletons, `uv` lock, Makefile, `.env.example`, and the two guard checks (holdout grep, no-test-modified) wired in `.github/workflows/ci.yml` | — | 1 | G0 | `chore/REPO-01-scaffold` |
| SPIKE-01 | backend | TigerVector spike on 20 docs | — | 1 | G0 | `feat/SPIKE-01-tigervector` |
| CORE-01 | backend | **Record contract freeze** (models, config, `.env.example`) | — | 1 | G0 | `feat/CORE-01-record-contract` |
| LLM-01 | backend | **Pluggable LLM boundary**: `get_chat_model(run_config)`, capability probe (tool-calling / usage reporting), JSON-schema fallback path, `token_source` labelling, rate-limit config | CORE-01 | 2 | G3 | `feat/LLM-01-provider-abstraction` |
| CORE-02 | backend | **Answer contract**: shared generation prompt + `{answer, explanation}` output schema used identically by P1/P2/P3, so EM/F1 score a short span and not prose | CORE-01 | 1 | G2 | `feat/CORE-02-answer-contract` |
| GRAPH-01 | backend | Schema + idempotent install, edge endpoints pinned | SPIKE-01 | 2 | G0 | `feat/GRAPH-01-schema` |
| GRAPH-02 | backend | Infobox parser + sport derivation + coverage report | GRAPH-01 | 2 | G1 | `feat/GRAPH-02-infobox-parser` |
| GRAPH-03 | backend | **Date normalizer** (shared with P3 — write once) | CORE-01 | 1 | G1 | `feat/GRAPH-03-date-normalizer` |
| GRAPH-04 | backend | Chunk + embed **all 2,951 docs** into TigerGraph | GRAPH-01 | 2 | G1 | `feat/GRAPH-04-chunk-embed` |
| GRAPH-05 | backend | Load vertices/edges; PREV/NEXT from `prev`/`next` | GRAPH-02, GRAPH-03 | 1 | G1 | `feat/GRAPH-05-load` |
| GRAPH-06 | backend | Vector-readiness gate (`/restpp/vector/status`) | GRAPH-04 | 1 | G1 | `feat/GRAPH-06-vector-gate` |
| GRAPH-07 | backend | Query library Q1–Q5 (`INTERPRET`, install once) | GRAPH-05, GRAPH-06 | 3 | G1 | `feat/GRAPH-07-query-library` |
| GRAPH-09 | backend | `BuildEvent` emitter for the 3-column build view | GRAPH-01 | 1 | G1 | `feat/GRAPH-09-build-events` |
| GRAPH-08 | backend | P2 pipeline: rule table → retrieval → generation → conformance | GRAPH-07, CORE-01 | 2 | G2 | `feat/GRAPH-08-p2-pipeline` |
| RAG-01 | backend | P1: unfiltered Q5 top-k → generation → citations → instrumentation | GRAPH-07, CORE-01 | 2 | G2 | `feat/RAG-01-p1-pipeline` |
| RAG-02 | backend | Unfiltered-behaviour guard test (protects AD-9) | RAG-01 | 1 | G2 | `feat/RAG-02-guard-test` |
| AGENT-01 | backend | Intent parser (function-calling + one retry) | CORE-01 | 3 | G4 | `feat/AGENT-01-intent-parser` |
| AGENT-02 | backend | Necessity router → LangGraph conditional edge | AGENT-01 | — | G4 | (with AGENT-01) |
| AGENT-03 | backend | Entity linking (longest-match, closed vocabularies) | AGENT-01, GRAPH-05 | 1 | G4 | `feat/AGENT-03-entity-linking` |
| AGENT-04 | backend | Tool agent nodes ×5 | GRAPH-07 | 2 | G4 | `feat/AGENT-04-tool-agents` |
| AGENT-05 | backend | Evidence evaluator + stopping criteria + strategy detector | AGENT-03, AGENT-04 | 3 | G4 | `feat/AGENT-05-evidence-loop` |
| AGENT-06 | backend | Trace recorder + token reconciliation | AGENT-05 | 1 | G4 | `feat/AGENT-06-trace` |
| AGENT-07 | backend | `StateGraph` assembly | AGENT-01…06 | 2 | G4 | `feat/AGENT-07-orchestrator` |
| AGENT-08 | backend | Paraphrase generalization set (~15) | AGENT-07 | 1 | G5 | `feat/AGENT-08-paraphrase-set` |
| EVAL-01 | backend | Name normalizer + multi-person splitter with Mc/Mac guard | CORE-01 | 1 | G3 | `feat/EVAL-01-normalizer` |
| EVAL-02 | backend | Scorer (EM, F1, P/R, Completeness-as-Recall, per-qtype) | EVAL-01 | 2 | G3 | `feat/EVAL-02-scorer` |
| EVAL-03 | backend | Dispatcher + Aggregator + verdict | CORE-01 | 2 | G2 | `feat/EVAL-03-dispatcher` |
| API-01 | backend | FastAPI routes + **API-key dependency** + stream tokens + SSE | EVAL-03 | 2 | G3 | `feat/API-01-fastapi` |
| EVAL-04 | backend | Batch runner (pool, backoff, resume, token ceiling) + store | EVAL-02, EVAL-03 | 3 | G5 | `feat/EVAL-04-batch-runner` |
| WEB-01 | frontend | Scaffold + query input + **3-column result renderer** + verdict strip | API-01 | 3 | G5 | `feat/WEB-01-three-column` |
| WEB-02 | frontend | Live trace panel (`EventSource`, strategy-change marker) | WEB-01, AGENT-06 | 1 | G5 | `feat/WEB-02-trace-panel` |
| WEB-03 | frontend | **3-column build view** (fan-out by `pipeline_affected`) | WEB-01, GRAPH-09 | 2 | G5 | `feat/WEB-03-build-view` |
| WEB-04 | frontend | **Dashboard: aggregate benchmark + per-question eval table (100 × 3)** | WEB-01, EVAL-04 | 3 | G5 | `feat/WEB-04-dashboard` |
| HID-01 | backend | Hidden 50-question run, holdout-protected | G5 | 1 | G6 | `feat/HID-01-holdout-run` |
| REPRO-01 | both | `make reproduce` + Dockerfile + CI | EVAL-04, WEB-04 | 1 | G6 | `feat/REPRO-01-reproduce` |
| DOC-01 | — | Architecture diagram | G4 | 1 | G6 | `docs/DOC-01-architecture` |
| DOC-02 | — | README (AD-9 honesty statement, prior-art positioning) | G5 | 1 | G6 | `docs/DOC-02-readme` |
| DOC-03 | — | `ATTRIBUTION.md` (CC BY-SA 4.0, corpus + derived data) | — | 1 | G6 | `docs/DOC-03-attribution` |
| DOC-04 | — | Demo video | G5, DOC-01 | 1 | G6 | — |

**Total: 62 pt** — backend 47 · frontend 9 · shared/docs 6.

> **This is 31 person-days against 3 calendar days.** Earlier revisions of this
> document quoted 46 pt; that figure was wrong — the table sums to 62 with the three
> foundation tasks review added (`REPO-01`, `CORE-02`, `LLM-01`). The cut
> ladder in §9 is not contingency, it is the plan. Expect to apply items 1–2 on
> day 2 and decide on 3–4 by midday on day 3.

---

## 6. The dashboard, in full

This is the graded artifact, so its contents are specified rather than implied.

**Aggregate benchmark view** (`WEB-04`, part 1)

| Element | Content |
|---|---|
| Headline panel | Overall EM/F1 per pipeline · median tokens per pipeline · **per-qtype accuracy gap beside per-qtype token multiplier** — the pair whose ratio decides "worth it" or "overkill" |
| Per-qtype matrix | EM, F1, Precision, Recall, Completeness × 5 qtypes × 3 pipelines |
| Accuracy-vs-tokens scatter | `tokens.total` (x) vs EM/F1 (y), one series per pipeline |
| Agentic behaviour | Step-count distribution · strategy-change frequency · stop-reason breakdown |

**Per-question eval table** (`WEB-04`, part 2) — **all 100 questions × 3 pipelines**

| Element | Content |
|---|---|
| Row | One evaluation question |
| Column groups | RAG · GraphRAG · Agentic — each with answer, EM, F1, precision/recall, tokens, latency, citation count; Agentic adds step count and `stop_reason` |
| Reference columns | Gold answer, `gold_doc_ids`, qtype |
| Filters | By qtype · by pipeline · **by "pipelines disagree"** — the disagreement filter is where the research question lives |
| Drill-down | Row click opens the full `TraceStep[]` for the agentic run and the retrieved document sets for all three |
| Hidden run | Same component renders the 50 hidden outputs, gold columns absent |

---

## 6a. Decisions this review forced

Three gaps were found that would have stopped implementation. All three are
resolved at the recommended option and recorded in DECISION-REGISTER §8.

### PLAT-06 — The answer contract (**critical — without it every EM score is ~0**)

Scoring is exact match with SQuAD normalization against gold answers like `5`,
`Men's marathon`, `26`. Nothing in any spec constrains generation output, so a
pipeline answering *"There were 5 biathlon events with more than 73
competitors"* scores **EM = 0** despite being correct. All three pipelines would
score near-zero, the comparison would be flat, and the core question would be
unanswerable.

**Resolved**: one shared generation contract (`CORE-02`) used **identically** by
P1, P2 and P3 — the model returns `{"answer": "<shortest span that answers the
question>", "explanation": "<prose with citations>"}`; EM and token F1 score
`answer` only; `explanation` is displayed and used for groundedness. The prompt
is byte-identical across pipelines apart from the retrieved context, because any
prompt difference becomes a confound in the measured gap.

### PLAT-07 — P2's routing signal

ARCHITECTURE-SPEC §2 and MODULE-BREAKDOWN GRAPH-09 route P2 by a "fixed
question-type → Q1/Q4/Q5 table". But `qtype` is an eval-set label, and NFR-7
forbids question-template regex in the answer path — so P2 as specified must
either read the test label or pattern-match the question. Both are prohibited.

| Option | Trade-off |
|---|---|
| **A (Selected)** P2 reuses the **same intent parser** as P3, then executes exactly one query with no evidence check, no fallback and no loop | Isolates the variable: the P3−P2 gap becomes purely the agentic loop, which is precisely what the core question asks about. Also removes a whole task |
| B Keyword heuristic, documented as the static rule table | Template matching by another name; hard to defend under NFR-7 in Q&A |
| C P2 always runs Q1 + Q5 regardless of question | Simple and honest, but so weak it stops being a meaningful middle comparator |

Option A makes the three-way comparison read as a clean ablation — P1 removes
the graph, P2 removes the loop, P3 has both — rather than three systems that
differ in several ways at once.

### PLAT-08 — Pluggable LLM: local or free-tier cloud

**Requirement**: the LLM must be swappable between a locally-hosted model and a
free cloud model, without code changes.

**Resolved**: provider abstraction at one boundary — `common/llm.py` exposes a
single `get_chat_model(run_config)` built on LangChain's provider-agnostic
initialiser. Provider, model, base URL and temperature come from configuration.
Nothing else in the codebase constructs a model client, so swapping providers is
a config edit and a rerun.

| Tier | Route | Note |
|---|---|---|
| Local | OpenAI-compatible server (Ollama, llama.cpp, vLLM) via `base_url` | Zero cost, no rate limits, fully offline reproduce path |
| Cloud free tier | Any provider with an OpenAI-compatible or LangChain-native integration | Faster and usually stronger tool-calling |

**Pluggable across runs, pinned within a run.** The abstraction is a *portability*
property, not a benchmarking one. Within one benchmark run the model is
identical across P1, P2 and P3, temperature 0, and the exact provider/model
string is written into the run header. A run whose model changed midway is void,
because the measured accuracy gap would then contain a model difference. The
dashboard labels every result set with the model that produced it.

**Pluggability breaks three things unless handled — all three are now tasks:**

| Problem | Why it bites | Resolution |
|---|---|---|
| **Function-calling support is not universal.** `AGENT-01` depends on structured tool-calling with one retry | Many local and some free-tier models either lack tool-calling or implement it unreliably. The intent parser is the entry point to P3, so this fails the whole agentic pipeline, not one feature | Capability probe at startup (`LLM-01`). If native tool-calling is present, use it. If not, fall back to JSON-schema prompting with the same Pydantic validation and the same single retry. Both paths emit the identical intent object, and the run header records which was used |
| **Token usage is not always reported.** `AGENT-06` reconciles per-step tokens against the record total | Local OpenAI-compatible servers frequently omit `usage`, which would silently zero the cost axis — the exact failure that makes the agentic path look free | `token_source` field per record: `provider` when usage metadata is returned, `local_tokenizer` when counted with the model's tokenizer as a fallback. The dashboard labels which. TECHNICAL-SPEC §11's "no estimation" rule holds wherever the provider reports; where it does not, the number is labelled rather than fabricated or dropped |
| **Free tiers rate-limit aggressively.** The batch pool assumes 6 concurrent questions | A 429 storm mid-run produces partial records and distorts latency | Pool size, requests-per-minute and backoff in `run_config`, defaulting to 2 concurrent on cloud free tiers and 6 locally. Already-written `qid`s are skipped on resume |

**Enterprise basis**: dependency inversion at the provider boundary, with
capability detection rather than capability assumption. A portable system that
silently degrades on a different provider is not portable.

---

## 7. Parallelism

**Three independent lanes from hour zero, no shared files:**

| Lane | Branches | Needs |
|---|---|---|
| TigerGraph | SPIKE-01 → GRAPH-01 → GRAPH-02/04 | Savanna workspace |
| Scoring | CORE-01 → EVAL-01 → EVAL-02 → EVAL-03 | **nothing** — no graph, no LLM |
| Intent | AGENT-01 → AGENT-03 | LLM provider only |

Once **G1**: RAG-01, GRAPH-08 and AGENT-04 are three independent consumers of
one query library — one assistant and one branch each.
Once **API-01**: WEB-01 builds against stubbed SSE while pipelines are still
being written; the G2 re-test against real output is a task, not an intention.
**Not parallelisable**: AGENT-05 → AGENT-06 → AGENT-07 is one chain.

| Failure mode | Guard |
|---|---|
| Two date normalizers get written | GRAPH-03 merges first; PLAN-003 imports it explicitly |
| An assistant "improves" P1 with a reranking retriever | RAG-02 asserts `p1_rag.py` imports no retriever class |
| An assistant reaches for `GraphCypherQAChain` | Stop condition in PLAN-003; dispatch is `operation → Q1–Q5` |
| An assistant introduces FAISS or Chroma "just for the spike" | Prohibited — TigerGraph holds the vectors; CI dependency allow-list |
| Usage silently zero when streaming | Reconciliation assertion: Σ `TraceStep.tokens` == record total |
| Records drift between modules | CORE-01 merges before any producer branch opens |
| Hidden set read during development | Holdout grep in CI |
| A test edited to make a build pass | No-test-modified check in CI |

---

## 8. Three-day sequence

| Day | Target | Gate |
|---|---|---|
| **1 am** | Repo init · vector spike · schema · contract freeze · scorer and intent parser started | G0 |
| **1 pm** | Parser + date normalizer + full embed running · scorer green on hand-computed fixtures · FastAPI skeleton with API-key dependency | **G3** |
| **2 am** | Query library callable; pub-001 replicates through GSQL · React scaffold against stubbed SSE | G1 |
| **2 pm** | P1 + P2 end-to-end · 3 columns render real output · first 100-question batch over 2 pipelines, scored | G2 |
| **3 am** | `StateGraph` assembly · one question per operation traced · trace panel live | G4 |
| **3 pm** | Full 3-pipeline run · dashboard + eval table · build view · paraphrase set | G5 |
| **3 eve** | Hidden 50 · `make reproduce` · diagram, README, video | G6 |

---

## 9. Cut ladder

Pre-decided, in order, so it is not a debate at 2am.

1. **Build view → single progress bar.** −2 pt. The search surface is the demo.
2. **Live trace panel → trace rendered from the completed record.** −1 pt.
3. **Dashboard aggregate charts → static images**, keeping the per-question
   eval table, which is the graded artifact. −1 pt.
4. **P3 restricted to LOOKUP / COUNT / ARGMAX**, multi_hop and temporal declared
   as known limitations in the README. −3 pt.

Never cut: scorer · batch runner · **per-question eval table** · **hidden-set
run** · `make reproduce`.

---

## 10. Corrections folded in from the data audit

- Both eval files use `qid` / `question` / `qtype` — the F-14 adapter is deleted
- `ground_truth` is `list[str]`, not `string`
- No `sport` field exists; derived from the title prefix (2,162/2,162)
- `date` and `dates` are two fields, 19% lack a year — normalizer added
- `prev`/`next` already present as years — resolution task reduced
- Venue+Games does **not** disambiguate (22.9% still ambiguous) —
  disambiguation request becomes the primary path
- 23 of 2,130 `competitors` values are non-integer — leading-int plus confidence
- `bronze2`/`bronzeNOC2` on ~13% of events — bronze becomes a set
- Completeness is Recall — reported as an explicit alias
- Corpus spans 1900–2022, not 1987–2022
- `chunks_returned` / `citations_count` added for the guidebook trace list
- `POST` cannot feed browser SSE — `POST → 202`, `GET …/stream` both surfaces
- `EventSource` cannot send headers — SSE uses short-lived stream tokens
- Build-phase LLM tokens are structurally **0** (local encoder, no LLM in
  ingestion) — reported as such, not hidden
