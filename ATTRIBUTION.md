# ATTRIBUTION

## Corpus

`data/corpus.jsonl` contains 2,951 documents derived from **English Wikipedia**,
converted to plain text. Each record carries its source article URL in the
`url` field and its Wikidata identifier in `wikidata_qid`.

Wikipedia text is licensed under
**[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/)**.

- **Attribution** — original authorship is the contributors of each linked
  English Wikipedia article. Per-document attribution is preserved: every
  record keeps its `url`, so any individual document can be traced to its
  source and revision history.
- **ShareAlike** — this obligation reaches **derived data**, not just the raw
  text. Anything generated from the corpus and redistributed — parsed infobox
  fields, chunked text, the graph load files, embeddings stored as vectors —
  carries the same CC BY-SA 4.0 terms. If those artifacts are published, they
  must be published under this licence with attribution intact.

## Evaluation sets

`data/eval_public.jsonl` (100 questions with answers) and
`acceptance/holdout/eval_hidden.jsonl` (50 questions without answers) were
supplied as hackathon resources. Their answers are defined **over the corpus**,
not over the real world: where a current Wikipedia article disagrees with
`corpus.jsonl`, the corpus is authoritative.

`acceptance/holdout/eval_hidden.jsonl` is a **holdout**. It is opened by
`backend/src/ogr/eval/batch_runner.py` and by nothing else — a CI check
enforces that no other file in the repository references that path. Reading it
during development would invalidate every number measured against it.

## Software

Third-party dependencies are declared in `backend/pyproject.toml` and
`frontend/package.json` and retain their own licences. Notable ones:
LangChain and LangGraph (MIT), pyTigerGraph (Apache-2.0),
sentence-transformers (Apache-2.0), React (MIT), Vite (MIT).

The embedding model `BAAI/bge-small-en-v1.5` is MIT-licensed.
