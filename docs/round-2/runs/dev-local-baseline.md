# Dev baseline on the local offline graph (2026-11-28)

**Dev only. Backend `local` (offline copy, no TigerGraph). These answers are not a submission and must not be used as one.**

## Setup

- Date: 2026-11-28 (UTC)
- Model: `nvidia/nemotron-3.5-super-vl-120b-a12b` (`LLM_MODEL`), `LLM_MAX_TOKENS=4096`
- Backend: `--backend local`, corpus `docs/round-2/data/corpus.jsonl`, questions `docs/round-2/data/questions_public.jsonl`
- Qids: the 36 with `dev` in `docs/round-2/data/public_split.json`. Run exit 0 on the first pass (no resume needed).
- Probe: one function-tool request returned `tool_calls` and `usage`, HTTP 200, about 2.9 s.
- Scorer: `r2-score --split dev` (own partial-credit F1 scorer). Scores in `out/r2/score_dev_local.json`.

## Headline numbers

- **Overall dev accuracy: 77.0%** over 36 questions (mean of per-question scores).
- Status match: 31/36. Perfect scores: 20. Zero scores: 2 (r2-pub-046, r2-pub-049, both status errors).
- Tokens per question (input + output): mean 13,187, median 9,344. Input mean 11,875, output mean 1,312.
- Latency: mean 13.1 s, p50 9.3 s, p95 24.9 s, max 68.2 s (r2-pub-037, 2 tool steps, so likely an LLM stall, not a tool).
- Tool steps per question (excluding `plan` and `llm_*`): mean 2.83, max 8.

## Per-question table

Status is ours / gold. Tokens are input / output. Tools are in call order. The note column is filled for score < 1.

| qid | status (ours / gold) | score | in tok | out tok | latency s | tool steps | tools (order) | note |
|---|---|---:|---:|---:|---:|---:|---|---|
| r2-pub-001 | answered / answered | 0.655 | 5,897 | 2,578 | 24.9 | 1 | repeat_winners | Over-inclusion: repeat_winners called with medal="" (any medal), returned 18 athletes vs 6 gold-medal winners; wrong key names (category vs event). |
| r2-pub-002 | answered / answered | 0.692 | 5,317 | 1,489 | 10.0 | 1 | repeat_winners | Over-inclusion: included bronze/silver medallists (Trillini, Kharlan, Velikaya); gold answer has only Vezzali and Szilágyi. |
| r2-pub-003 | answered / answered | 1.000 | 8,359 | 1,184 | 8.3 | 1 | find_events |  |
| r2-pub-005 | answered / answered | 1.000 | 6,528 | 724 | 5.8 | 1 | find_entities |  |
| r2-pub-006 | answered / answered | 0.500 | 7,049 | 979 | 8.9 | 1 | medals_by_nation | Format: "Japan" instead of NOC code JPN in a prose answer; count 8 correct. |
| r2-pub-008 | answered / answered | 0.111 | 8,408 | 1,316 | 9.3 | 1 | find_events | Format: country names instead of NOC codes (AUS, CAN, ...); count 8 correct. |
| r2-pub-009 | answered / answered | 0.769 | 11,058 | 1,900 | 16.8 | 2 | event_series, find_events | Shape: uses most/fewest keys and editions list; gold uses max_year/min_year rows; values correct. |
| r2-pub-011 | answered / answered | 0.941 | 10,026 | 1,664 | 11.1 | 5 | find_events, event_series, find_events, find_events, text_search | Shape: maximum/minimum keys, extra note and a 2028 "synthetic" flag; values match gold. |
| r2-pub-012 | answered / answered | 1.000 | 5,529 | 964 | 7.3 | 1 | event_series |  |
| r2-pub-013 | answered / answered | 1.000 | 5,390 | 963 | 7.6 | 1 | athlete_medals |  |
| r2-pub-014 | answered / answered | 1.000 | 5,026 | 602 | 5.0 | 2 | athlete_medals, find_events |  |
| r2-pub-015 | answered / answered | 1.000 | 4,945 | 635 | 5.9 | 1 | athlete_medals |  |
| r2-pub-017 | answered / answered | 1.000 | 7,932 | 1,212 | 10.1 | 1 | find_entities |  |
| r2-pub-018 | answered / answered | 1.000 | 6,902 | 1,067 | 8.5 | 2 | entity_facts, entity_facts |  |
| r2-pub-022 | answered / answered | 1.000 | 12,027 | 1,096 | 8.1 | 3 | text_search, find_events, athlete_medals |  |
| r2-pub-023 | answered / answered | 1.000 | 10,346 | 1,061 | 8.1 | 2 | find_events, text_search |  |
| r2-pub-024 | answered / answered | 1.000 | 6,605 | 1,322 | 10.4 | 2 | find_events, text_search |  |
| r2-pub-025 | partial / answered | 0.500 | 78,869 | 6,701 | 50.3 | 8 | find_events, rank_rows, find_events, find_events, find_events, find_events, read_document, read_document | Status: answered "partial"; gold is "answered". Answer (Men's decathlon, 13) is correct. 8 tool steps, 78.9k input tokens. |
| r2-pub-026 | answered / answered | 1.000 | 13,452 | 1,244 | 10.6 | 1 | find_events |  |
| r2-pub-028 | not_in_corpus / not_in_corpus | 1.000 | 46,129 | 1,371 | 14.2 | 6 | find_events, find_events, find_events, text_search, find_events, text_search |  |
| r2-pub-029 | partial / partial | 0.444 | 13,458 | 1,265 | 11.5 | 7 | find_events, find_events, find_events, find_events, find_events, find_events, find_events | Shape: year-keyed strings "Keiji Suzuki (JPN)" / "not in corpus" instead of found / not_in_corpus lists; content correct. |
| r2-pub-030 | answered / answered | 1.000 | 8,993 | 632 | 6.4 | 3 | entity_facts, find_entities, text_search |  |
| r2-pub-032 | answered / answered | 1.000 | 7,319 | 660 | 6.5 | 3 | repeat_winners, find_events, repeat_winners |  |
| r2-pub-033 | answered / answered | 0.500 | 5,255 | 686 | 5.7 | 1 | medals_by_nation | Format: "The Netherlands" in prose instead of NOC code NED; count 4 correct. |
| r2-pub-036 | answered / answered | 1.000 | 5,484 | 597 | 10.1 | 2 | find_events, find_events |  |
| r2-pub-037 | answered / answered | 1.000 | 6,313 | 832 | 68.2 | 2 | find_events, find_events |  |
| r2-pub-038 | answered / answered | 1.000 | 5,789 | 475 | 5.8 | 1 | find_events |  |
| r2-pub-042 | answered / answered | 1.000 | 5,773 | 1,019 | 9.2 | 2 | find_events, text_search |  |
| r2-pub-043 | answered / answered | 0.667 | 5,460 | 2,160 | 17.2 | 3 | text_search, text_search, text_search | Missing item: says the directory entry is not authoritative but does not state that the signed July 1 assignment establishes Carson Velodrome. |
| r2-pub-044 | answered / answered | 0.333 | 12,976 | 868 | 8.0 | 3 | find_events, source_records, text_search | Missing item: gives "Carson Velodrome" without the basis (signed July 1 allocation supersedes the June 15 draft). |
| r2-pub-045 | answered / answered | 0.800 | 10,401 | 1,103 | 12.9 | 3 | find_events, text_search, read_document | Missing item: 31 nations omitted from the structured answer; keys named registered_entries / athletes_competed. |
| r2-pub-046 | partial / not_in_corpus | 0.000 | 17,875 | 1,386 | 21.8 | 8 | find_events, text_search, source_records, read_document, text_search, text_search, text_search, text_search | Status: "partial" where gold is "not_in_corpus". Explanation is correct (names not in corpus) but the status is wrong, so score 0. |
| r2-pub-047 | partial / answered | 0.500 | 21,508 | 1,776 | 16.8 | 8 | text_search, text_search, source_records, find_events, text_search, text_search, find_events, source_records | Missing item / wrong conclusion: says the corpus gives no reason for 42 vs 40; gold reason is that the newsletter confused registered slots with confirmed competitors. |
| r2-pub-048 | answered / partial | 0.300 | 12,210 | 1,834 | 14.8 | 5 | find_events, text_search, read_document, text_search, source_records | Status: "answered" where gold is "partial". Content (two unverified claims, nothing confirmed) is close to gold. |
| r2-pub-049 | answered / not_in_corpus | 0.000 | 13,859 | 896 | 8.3 | 5 | find_events, text_search, text_search, text_search, read_document | Status: "answered" where gold is "not_in_corpus". Says no official stoppage exists; status wrong, so score 0. |
| r2-pub-050 | answered / answered | 1.000 | 9,017 | 979 | 8.7 | 3 | text_search, text_search, read_document |  |

## Failure kinds (score < 1, 16 questions; one primary kind each)

- **Medal scope: over-inclusion (any medal counted, not gold): 2** (001, 002)
- **Format: country names or prose instead of NOC codes: 3** (006, 008, 033)
- **Answer shape or key names differ from gold: 3** (009, 011, 029)
- **Wrong status (partial / answered / not_in_corpus): 4** (025, 046, 048, 049)
- **Missing item or wrong conclusion in an explanation: 4** (043, 044, 045, 047)

Total: 16 questions. Two of the status errors (046, 049) also scored 0.

Observations:

- Medal scope is a tool-parameter choice: `repeat_winners` was called with `medal=""`, which pulls in silver and bronze. That is a prompt or tool-use issue for a later round of fixes fix. Not changed here.
- The status field is the largest single cost on this set: 4 questions lost most of their score on status alone, including 025, whose answer is correct.
- Cost: r2-pub-025 (78.9k input tokens, 8 steps) and r2-pub-028 (46.1k) are the heaviest; the mean input is about 11.9k per question.
- Nothing here was changed in prompts or code. Findings only.

