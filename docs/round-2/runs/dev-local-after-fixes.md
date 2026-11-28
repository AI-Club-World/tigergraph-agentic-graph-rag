# Dev run on the local backend after general prompt/tool fixes (2026-11-28)

**Dev only. Backend `local`, 36 dev qids of `public_split.json`. Not a submission.** The `check` split and the hidden file were not touched.
Model `nvidia/nemotron-3.5-super-vl-120b-a12b`, 4 workers. Scores: `r2-score --split dev`.

## Before / after (same command, same 36 questions)

| Run | Accuracy | Status match | Tokens mean / median | Latency mean / p95 (4 workers) |
|---|---:|---:|---:|---:|
| before (baseline code, re-run) | 80.5 | 32/36 | 13,081 / 8,920 | 25.0 s / 42.7 s |
| iteration 1 | 92.8 | 35/36 | 12,139 / 9,560 | 22.3 s / 43.8 s |
| iteration 2 (extra status/basis rules) | 89.7 | 34/36 | 14,982 / 10,064 | 24.9 s / 50.0 s |
| iteration 3 (final, kept) | 90.8 | 34/36 | 12,543 / 9,614 | 22.9 s / 46.4 s |

The earlier baseline run scored 77.0; the temperature-0 model is still noisy between runs (about +-3 points), so differences of 1-3 points between iterations are not significant. The final code is iteration 3: higher than before on accuracy and status match, tokens about 4% lower. Iteration 1 was the best single run, but iteration 3 keeps the additional rules for the status and as-of failures that iteration 1 still showed.

## Failure groups and changes

| Group (questions) | Root cause | Change (general, no question wording) |
|---|---|---|
| Medal scope (001, 002, 032) | `repeat_winners` was called with `medal=""` (any medal); "won" was read as "medalled" | `medal` parameter doc: empty = ANY medal, "won an event" means gold unless the question is about medals/podium; prompt rule on scope (person, sport, years, first place) |
| NOC codes (006, 008, 033) | model wrote country names in prose | prompt: name nations by the NOC codes tools return; `medals_by_nation` doc says the same; tools' field names kept in answers |
| Shape (009, 011, 012, 029) | free-form key names | prompt: per-year counts/extremes as `{rows:[{year,value}], max_year, min_year}`; found vs missing items listed separately |
| Truncation / missing rows (025) | `find_events` showed 33 of 48 rows; the model ranked an incomplete view | `compact_result` drops fields that repeat another field (`event_id`, `athlete_id`, `title` when `event_name` exists, `games` when `year` exists, `event` when `event_name` exists), so more rows fit and each costs fewer tokens; truncation note says `rank_rows` sees all rows; `rank_rows` doc says rows lacking the field are unknown, not zero |
| Status (025, 046, 048, 049) | status policy text too thin | prompt: answered = corpus gives what was asked even if many rows compared; partial = parts missing or only unverified/conflicting accounts; not_in_corpus = the specific thing asked is absent although context exists |
| Missing items / basis (043, 044, 045, 047) | answer omitted the basis; multi-term `text_search` (AND) returned nothing | prompt: put the basis (authoritative source, effective record, what each figure counts) in the answer; `text_search` doc: terms are ANDed, use 1-3 distinctive terms, retry with fewer; caveats stay in the explanation |

Tests: `test_compact_drops_fields_that_repeat_another_field`, `test_truncation_note_points_to_rank_rows_over_all_rows` (tests/r2/test_agent_core.py). `PROMPT_VERSION` is now `r2-agent-v2`. Suite 950 passed, ruff clean.

## Remaining imperfect questions in iteration 3 and why left

- Answer shape that the gold fixes but the question does not state (e.g. which key names; event+winner pairs vs event names only; 003, 009, 012): left, a prompt rule per shape would be overfitting.
- Team events counted for a person's medals (013, 015: gold lists individual events only): left, the corpus does not distinguish and a rule would be a guess.
- Unverified-accounts status (048) and why-questions (047, 043, 044): the model still flips between partial/answered and drops the basis in some runs; the rules are in, residual variance remains.
- Run-to-run variance is about 3 points; a fourth iteration would only fit noise (limit of 3 iterations).

Outputs: `out/r2/dev_local_w2_{before,it1,it2,it3}.jsonl` (untracked scratch).
