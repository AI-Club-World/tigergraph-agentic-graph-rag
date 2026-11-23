# Agentic GraphRAG Hackathon: Round 2 brief

Congratulations on reaching Round 2. Round 1 showed that every finalist can answer one-field questions. Round 2 tests whether your system can **reason across many documents, weigh sources that disagree, track facts that change over time, and say honestly when the corpus does not contain an answer.**

## Key dates

The submission deadline and the judging-call schedule are in the message this folder came with.

## What you get

Everything comes in this one folder. Nothing else will be released later.

| File | What it is |
|---|---|
| `corpus.jsonl` | **The full Round 2 corpus: 3,530 documents.** It contains all 2,951 Round 1 documents (unchanged) plus 579 new ones: 299 Paris 2024 and 114 Milano Cortina 2026 event articles (real, from Wikipedia), 127 LA 2028 event articles (fictional), and 39 LA 2028 source records (fictional; see below). Use this file in place of your Round 1 corpus. |
| `questions_public.jsonl` | **50 questions with answers.** Each has the expected `status` (`answered`, `partial` or `not_in_corpus`), the answer, the documents that support it, and sometimes a short note. Use them to build and test your system. |
| `questions_hidden.jsonl` | **50 questions without answers.** Run your system on them and send us the results. We score them against our own answer key. |

## About the data

- **The LA 2028 documents are fictional.** They're marked `"synthetic": true`, and each one opens with a notice. The athletes, results and incidents are invented for this hackathon. A model's memory can't help with them; only retrieval can. Their `url`, `wikidata_qid` and `wikipedia_pageid` are `null`, so key on `doc_id`.
- **The LA 2028 source records** are short documents such as scoreboard captures, jury decisions, schedules, bulletins, registration extracts, news items, blog posts and emails. Each one gives its **source** and its **publication time**. Like real sources, some are provisional, out of date or simply wrong, and none of them says so about itself. Your system has to decide which evidence to trust.
- **The corpus is the only source of truth.** If the corpus and the real world disagree, the corpus wins. If the corpus does not contain an answer, the correct response is to say so.

## What Round 2 tests

A successful answer may not be a single name or number. It may need to explain which facts are reliable, which are disputed, what was true at a particular time, and what cannot be established.

| Challenge | What the agent must demonstrate |
|---|---|
| Incomplete information | Distinguish unknown information from a negative fact |
| Conflicting information | Identify disagreements and assess the evidence |
| Temporal changes | Distinguish original, revised and current facts |
| Source reliability | Differentiate provisional claims from official decisions |
| Combined reasoning | Reconcile multiple documents before reaching a conclusion |

## The questions

The questions come **without any type label** and in varied wording. The public 50 show every style in the hidden 50:

- **Short factual answers:** a name, a country or a number
- **Complete lists:** every item, not the top few
- **Counts and comparisons:** e.g. which nation won the most golds in a sport at a given Games
- **Trends across Games:** e.g. how participation changed over the years, with the peak and the low point
- **Athlete careers** traced across many event documents
- **Film and politician questions:** these documents have been in the corpus all along
- **"Why" questions** whose answer is only in the article text
- **Partly answerable questions:** answer what the corpus supports and say clearly what is missing
- **Questions the corpus cannot answer:** reply `not_in_corpus`. An invented answer scores 0.
- **Indirect evidence:** some facts appear only in another article
- **Sources that disagree or change over time:** give the answer that the most authoritative evidence supports for the time the question asks about, and say what was provisional, superseded or never confirmed

## What to submit

Run your system on **both** question sets, then submit the six items below by the deadline.

**1. `answers_public.jsonl`:** your system's answers to the 50 public questions.

**2. `answers_hidden.jsonl`:** your system's answers to the 50 hidden questions.

Both files use the same format: one JSON object per question, one per line, every field filled in:

```json
{"qid": "r2-pub-006", "status": "answered", "answer": "Japan (JPN), with 8 golds",
 "explanation": "Counted gold medals by nation across all 18 wrestling events at the 2024 Games.",
 "citations": ["Q117156534", "Q117156536"], "input_tokens": 3400, "output_tokens": 210, "latency_ms": 5200,
 "trace": [
   {"step": 1, "tool": "plan", "tigergraph": false, "input_tokens": 1200, "output_tokens": 60, "ms": 900},
   {"step": 2, "tool": "count_golds_by_nation", "tigergraph": true, "query": "golds_by_nation",
    "params": {"sport": "Wrestling", "year": 2024}, "rows": 18, "ms": 140},
   {"step": 3, "tool": "llm_answer", "tigergraph": false, "input_tokens": 2200, "output_tokens": 150, "ms": 1900}]}
```

- **`status`:** `answered`, `partial` (some of it is missing from the corpus) or `not_in_corpus`
- **`answer`:** the complete answer, in plain text or JSON
- **`explanation`:** a short account of how you reached the answer
- **`citations`:** the `doc_id`s that support the answer
- **`input_tokens`, `output_tokens`:** all LLM tokens used for this question, summed over every call (including planning, tool selection and retries)
- **`latency_ms`:** wall-clock time from receiving the question to returning the answer
- **`trace`:** every step your system took to answer this question (see **Traces** below)

**Traces.** Every answer must include the full trace of how your system produced it: one entry per step, in order, written by your code as it runs (not reconstructed afterwards). Each step has:

| Field | Required for | What it is |
|---|---|---|
| `step` | every step | Step number: 1, 2, 3, … |
| `tool` | every step | The tool or stage, e.g. `plan`, `vector_search`, `run_gsql`, `llm_answer` |
| `tigergraph` | every step | `true` if this step queried TigerGraph, otherwise `false` |
| `query` | TigerGraph steps | The installed query name, or the GSQL / REST call |
| `params` | TigerGraph steps | The parameters passed |
| `rows` | TigerGraph steps | The number of rows or vertices returned |
| `input_tokens`, `output_tokens` | LLM steps | Tokens for this call |
| `ms` | every step | Time the step took |

- **Token totals add up.** The LLM steps' tokens must add up to the answer's `input_tokens` and `output_tokens`.
- **Timings line up.** Step times should roughly add up to `latency_ms`.
- **TigerGraph steps get checked.** Each one must appear in your TigerGraph query log (item 5).
- **No TigerGraph step means a closer look.** Answers whose trace has no TigerGraph step will be checked closely.

**3. `metrics.json`:** a summary of both runs, computed from the two answer files:

```json
{
  "public": {
    "questions": 50,
    "accuracy_pct": 82.0,
    "accuracy_method": "how you judged correctness against the published answers",
    "not_in_corpus_answers": 2,
    "input_tokens_total": 150000, "output_tokens_total": 12000,
    "tokens_per_question_avg": 3240,
    "latency_ms_avg": 4800, "latency_ms_p50": 3900, "latency_ms_p95": 11000,
    "llm_calls_per_question_avg": 2.4,
    "tigergraph_queries_per_question_avg": 3.1,
    "trace_steps_per_question_avg": 5.2,
    "answers_with_tigergraph_step": 48,
    "total_run_time_s": 260,
    "cost_usd_total": 0.42
  },
  "hidden": {
    "questions": 50,
    "accuracy_pct": null,
    "not_in_corpus_answers": 6,
    "input_tokens_total": 160000, "output_tokens_total": 13000,
    "tokens_per_question_avg": 3460,
    "latency_ms_avg": 5100, "latency_ms_p50": 4100, "latency_ms_p95": 12500,
    "llm_calls_per_question_avg": 2.5,
    "tigergraph_queries_per_question_avg": 3.3,
    "trace_steps_per_question_avg": 5.4,
    "answers_with_tigergraph_step": 47,
    "total_run_time_s": 275,
    "cost_usd_total": 0.45
  }
}
```

- **Public accuracy** is your own measurement against the published answers. Say how you measured it. We re-check it with our key.
- **Hidden accuracy** stays `null`: we score the hidden answers ourselves.
- **Every other number** must match the per-question values in your answer files. We recompute them from those files, and a mismatch counts against repeatability.
- **Both runs** must use the same code and the same settings.

**4. A git tag** on your repo, created at the deadline, for the code that produced both answer files.

**5. Your TigerGraph query log** from both runs (the RESTPP / GSQL log, or your client's request log with timestamps). The timestamps should match your traces.

**6. Your graph's vertex and edge counts** by type, after loading `corpus.jsonl`.

## How you are scored

We check your hidden-set answers against our answer key, **fact by fact with partial credit**. Lists must be complete, and adding wrong items lowers the score.

| Category | Weight |
|---|---|
| Answer accuracy on the hidden set (scored by us) | 40% |
| Honesty: correct `not_in_corpus`, no invented answers | 10% |
| Evidence: citations that actually support the answer | 10% |
| Repeatability: clean setup, locked dependencies, complete traces and logs, and live reproduction in the judging call | 15% |
| Efficiency: tokens, latency and cost per question, on both sets | 10% |
| Live judging: architecture and demo | 15% |

## Requirements for your system

1. **TigerGraph must be used when answering,** not only for loading. Keep the TigerGraph query log from both runs.
2. **One-command build and run,** so your results can be reproduced (judges may ask you to run it live):
   ```bash
   ./build.sh corpus.jsonl
   ./run.sh questions_public.jsonl answers_public.jsonl
   ./run.sh questions_hidden.jsonl answers_hidden.jsonl
   ```
3. **Locked dependencies** (a lock file or exact versions) and a `.env.example` listing every key you need.
4. **No question-specific rules.** No regexes on question wording, no use of question IDs, and no answers built into the code. In the judging call your system must answer new questions it has never seen, so tuning to the hidden 50 won't help, and the judges will check the code.
5. Your README must describe the architecture: how documents become graph data, which tools the agent has, and how it decides what to do next.
6. **Live reproduction in the judging call.** Be ready to screen-share your system with TigerGraph running and the full corpus loaded. Judges will:
   - give you a few **new questions you haven't seen** and watch your system answer them;
   - pick a few of your **hidden-set questions** and check that your system reproduces your submitted answers and traces.

   **Answers that your system cannot reproduce, or that were produced outside your system (by hand, or by pasting the corpus or questions into a general AI assistant), are disqualified.** Using AI tools to *write your code* is fine. The answers must come from your system.

Questions: reply to the message this folder came with.
