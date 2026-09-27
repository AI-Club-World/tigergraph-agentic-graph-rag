# Hackathon Resources

| Path | Contents |
|---|---|
| `corpus/corpus.jsonl` | 2,951 documents, 5,466,414 tokens (the sum of each record's `approx_tokens`) |
| `questions/eval_public.jsonl` | 100 questions, with answers |
| `questions/eval_hidden.jsonl` | 50 questions, without answers |

All three files are JSONL: one JSON object per line. Each corpus record has
`doc_id` (the Wikidata QID), `title`, `url`, `wikidata_qid`,
`wikipedia_pageid`, `approx_tokens` and `text`. Each question has `qid`,
`question` and `qtype`. The public set also has its gold answers and gold
document ids.

## The corpus is the only source of truth

Answers are defined over these documents. They are not defined over the real
world, and not over what a model remembers. If Wikipedia today disagrees with
`corpus.jsonl`, the corpus wins.

The documents are English Wikipedia articles converted to plain text. Most are
Olympic event articles whose infobox is kept at the top of the text. The years
named in document titles run from 1900 to 2022, and almost all fall between
1988 and 2022. The subject matter is narrow, so read some documents before you
design anything.

## Attribution

The corpus text is derived from English Wikipedia and licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Each document
carries its source URL. See `../ATTRIBUTION.md`.

## Dataset names

A dataset's id is its file stem (`corpus/<id>.jsonl`). The name the UI shows
is resolved in this order, and the first match wins:

1. A title typed on upload or rename, stored in `corpus/<id>.meta.json`.
2. A `dataset`, `collection` or `corpus` field that most records carry.
3. A name inferred from the documents: the URL source, the term most titles
   share and the years they span (e.g. *Wikipedia · Olympics · 1900–2022*).
4. The file stem.

Uploads that share a file name get distinct ids (`corpus-2`, …).
