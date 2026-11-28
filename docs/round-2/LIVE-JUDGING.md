# Round 2 — Live Judging Runbook (15-Minute Call)

Concise operational runbook for the live judging call: screen-sharing the running system, walking through the architecture, answering unseen judge questions live, and reproducing submitted hidden-set answers.

---

## 1. 15-Minute Call Plan

| Window | Duration | Activity |
|---|---:|---|
| 0:00 – 1:00 | 1 min | Intro, confirm tagged commit (`round2-submission`), show `/r2/status` healthy |
| 1:00 – 4:00 | 3 min | Architecture walkthrough (corpus -> graph -> tools -> agent -> guards) |
| 4:00 – 9:00 | 5 min | Answer 2–3 **new** judge questions live in the Web UI (`/round2`) and inspect traces |
| 9:00 – 13:00 | 4 min | Reproduce 1–2 **hidden-set** questions via `r2-run --qids` and compare against submitted `answers_hidden.jsonl` + `out/r2/tg_query_log.jsonl` |
| 13:00 – 15:00 | 2 min | Q&A on limits, anti-overfitting, and design choices |

---

## 2. Pre-Call Checklist

Run through this 15 minutes before the call:

1. **Kaggle LLM server (`kaggle_server.py`):**
   - Running in `MODE = "serve"` with `ENABLE_EMBEDDINGS = False`, `ENABLE_CHAT = True`, `CHAT_CONTEXT = 32768`.
   - Verify `GET <tunnel_url>/health` returns HTTP 200 and `GET <tunnel_url>/chat/status` returns a valid test generation.
2. **`.env` at repo root:**
   - `LLM_PROVIDER=openai_compatible`
   - `LLM_BASE_URL=<tunnel_url>/v1`
   - `LLM_MODEL=<CHAT_MODEL>` (exact tag used for the submission runs)
   - `LLM_TEMPERATURE=0`
   - Same `R2_MAX_STEPS` (default `8`) and TigerGraph credentials as the submission run.
3. **TigerGraph Cloud workspace:**
   - Confirm the workspace is **awake** in the TigerGraph Cloud console (auto-start disabled workspaces return HTTP 500 when asleep).
   - Start backend on `:8000` and verify:
     ```bash
     curl -s http://127.0.0.1:8000/r2/status
     ```
     Confirm `"schema_installed": true` and `"error": null`.
4. **Full Round-2 corpus loaded:**
   - Corpus (`3,530` docs) loaded via `./build.sh docs/round-2/data/corpus.jsonl`.
   - Keep `out/r2/graph_counts.json` open and verified against live graph counts.
5. **Web UI & API:**
   - Open `http://localhost:5173/round2` (**"Round 2 agent"** page, mock mode off) with the backend running on `:8000`.
6. **Terminal & reference files ready:**
   - Terminal at repo root on the tagged commit (`round2-submission`, clean working tree).
   - Ready to open: `answers_hidden.jsonl`, `out/r2/tg_query_log.jsonl`, `out/r2/metrics.json`, `out/r2/graph_counts.json`.
   - Key code files ready in editor: `backend/src/ogr/r2/agent.py`, `backend/src/ogr/r2/tools.py`, `backend/src/ogr/graph/schema_r2_answer.gsql`, `backend/src/ogr/graph/queries/r2_medals_by_nation.gsql`.

---

## 3. 3-Minute Architecture Walkthrough Script

1. **Documents to graph data (`ogr.r2.corpus_model`, `ogr.r2.build`):**
   - Deterministic single pass over `corpus.jsonl` — **no LLM, no embeddings**.
   - Reuses Round-1 types (`Document`, `Chunk`, `OlympicEvent`, `Games`, `Sport`, `Venue`) and adds via `schema_r2_answer.gsql`:
     - `Athlete` and `WON` (`Athlete -> OlympicEvent` with `medal`, `noc`, `place`, `event_key`).
     - `SourceRecord` (the LA 2028 records with `source_name`, deterministic `authority` class from `Source:`, `published_at`, `published_text`, `text`) and `REPORTS_ON` (`SourceRecord -> OlympicEvent`).
     - `Entity` and `Claim` (`Document -ASSERTS-> Claim -ABOUT-> Entity`) for every non-Olympic infobox (films, officeholders, people).
2. **Ten TigerGraph tools + local helper (`ogr.r2.tools`):**
   - Each read tool is one installed `r2_*` GSQL query: `find_events`, `medals_by_nation`, `event_series`, `athlete_medals`, `repeat_winners`, `entity_facts`, `find_entities`, `source_records`, `text_search`, `read_document`.
   - Plus local deterministic helper `rank_rows` (sorts/slices an earlier result; recorded as `tigergraph: false`) and `finish`.
   - Results return as compact JSON: empty fields dropped, capped at **60 rows**, **2,000 chars** per text field, **24,000 chars** total, with explicit `truncated` notes so the model knows when to narrow or call `read_document`.
3. **How the agent decides (`ogr.r2.agent`):**
   - Short general `SYSTEM_PROMPT` + question sent to the chat model with native tool calling at temperature `0`.
   - No question-specific rules and no hand-written router: the model chooses tools (several in parallel when independent) up to `R2_MAX_STEPS` (`8`), after which `finish` is forced.
4. **Statuses & deterministic guards (`_finalize`):**
   - Statuses: `answered` (fully supported), `partial` (some requested parts missing), `not_in_corpus` (nothing in corpus answers it).
   - Guards: `citations` are filtered strictly to `doc_id`s returned by tools in that question; `not_in_corpus` forces `answer: null`; an empty answer forces `status: "not_in_corpus"`; an unknown status becomes `partial`; per-question exceptions are fault-isolated so one failure never aborts a batch run.

---

## 4. Answering a New Judge Question Live

- **Web UI (primary):** On `http://localhost:5173/round2` (**"Round 2 agent"**), type the judge's question and click **Ask**.
- **API (alternative):** Note that `r2-run` takes a JSONL file, whereas `POST /r2/ask` takes one ad-hoc question:
  ```bash
  curl -s -X POST http://127.0.0.1:8000/r2/ask \
    -H "Content-Type: application/json" \
    -d '{"question": "<JUDGE_QUESTION>", "backend": "tigergraph"}'
  ```
- **What to point out in the result & trace:**
  1. **Status badge** (`Answered`, `Partial`, or `Not in corpus`) and `Answer` body (text, table, or JSON).
  2. **Trace steps:**
     - LLM steps (`plan`, `llm_step`, `llm_answer`) with per-call `input_tokens` / `output_tokens` that sum exactly to the totals.
     - Graph steps showing the green **`TigerGraph`** badge (`tigergraph: true`), installed `query` (`r2_*`), `params`, `rows`, and `ms`.
  3. **Citations:** Every `doc_id` shown was actually returned by a tool step in that run.

---

## 5. Reproducing a Submitted Hidden Answer

Run a single `qid` to fresh scratch paths in `/tmp` so submitted files (`answers_hidden.jsonl`, `out/r2/tg_query_log.jsonl`) are untouched:

```bash
cd backend && python3 -m ogr.cli r2-run \
  --questions ../docs/round-2/data/questions_hidden.jsonl \
  --out /tmp/repro.jsonl \
  --qids <QID> \
  --query-log /tmp/repro_tg_log.jsonl
```

Compare against the submitted artifacts:
- **Answer & trace:** Compare `/tmp/repro.jsonl` with the matching `qid` line in `answers_hidden.jsonl` (status, answer, citations, trace tool sequence, `query`, `params`, `rows`).
- **Query log:** Compare `/tmp/repro_tg_log.jsonl` with the matching `qid` lines in `out/r2/tg_query_log.jsonl` (`qid`, `step`, `query`, `params`, `rows`, `ts` UTC timestamp inside the trace window).

---

## 6. Likely Judge Questions & Honest Answers

- **Why isn't output bit-for-bit identical even at temperature 0?**
  GPU/inference batching and provider-side scheduling can still introduce minor phrasing or token-count differences at `temperature=0`, though tool selection and graph rows remain deterministic for the same query parameters.
- **How are conflicting LA 2028 source records handled?**
  `SourceRecord.authority` (`official`, `operational`, `secondary`, `unreliable`, `unclassified`) and `published_at` are extracted deterministically at build time from the `Source:` line; per our D4 deviation, the answering LLM weighs authority, publication time, and effective time at answer time rather than running a pre-built resolution engine.
- **Why are there no embeddings in the Round-2 path?**
  `build.sh` and `run.sh` use structured GSQL queries plus `text_search` and `read_document` directly against TigerGraph so `build.sh` needs only TigerGraph and the corpus. Tradeoff: `text_search` requires all given terms to match case-insensitively (exact-term matching rather than semantic similarity).
- **How do you prevent overfitting to the public/hidden sets?**
  Rule 4 compliance: zero regexes on question wording, zero `qid` references, and zero hardcoded answers in `backend/src/ogr/r2/` (checked by anti-overfitting tests); the public 50 are split into `dev` and `check` (`docs/round-2/data/public_split.json`).
- **How reliable is `public` accuracy in `metrics.json`?**
  It is our own proxy fact-level scorer (`ogr.r2.score`), not the official judge key; `hidden` accuracy is `null`. Never claim unmeasured live results.

---

## 7. Fallback Plan Mid-Call

- **If the Kaggle LLM tunnel drops:**
  1. Check Kaggle notebook output for a new Quick Tunnel URL (`*.trycloudflare.com`), update `LLM_BASE_URL` in `.env`, and restart `uvicorn`.
  2. If Kaggle is down, switch `.env` to a backup OpenAI-compatible/cloud provider and restart `uvicorn`. Be transparent with the judges about the provider switch.
- **If TigerGraph stops or times out (HTTP 500):**
  1. Wake the workspace in the TigerGraph Cloud console while walking through the architecture, GSQL schema/queries, and pre-recorded submitted traces/query logs.
  2. Re-verify `GET http://127.0.0.1:8000/r2/status` returns `"schema_installed": true` before resuming live queries.
  3. **Never** pass `--backend local` off as a live TigerGraph run (its trace steps carry `tigergraph: false` and write no query log).
