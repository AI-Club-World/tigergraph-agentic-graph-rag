# ATTRIBUTION

## Corpus

`data/corpus/corpus.jsonl` contains 2,951 documents derived from **English
Wikipedia** and converted to plain text. Each record carries its source article
URL in `url`, its Wikidata identifier in `wikidata_qid` and its Wikipedia page
id in `wikipedia_pageid`.

Wikipedia text is licensed under
**[Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/)**.

- **Attribution.** The original authors are the contributors to each linked
  English Wikipedia article. Every record keeps its `url`, so any document can
  be traced to its source and revision history.
- **ShareAlike.** This obligation also covers **derived data**, not just the
  raw text. Anything generated from the corpus and redistributed carries the
  same CC BY-SA 4.0 terms: parsed infobox fields, chunked text, graph load
  files, stored embeddings. If you publish those artifacts, publish them under
  this licence with attribution intact.

Datasets uploaded through the Build screen (`data/corpus/<id>.jsonl`) keep
whatever licence their source carries. This file covers only the supplied
corpus.

## Evaluation sets

Two question sets were supplied as hackathon resources:

- `data/questions/eval_public.jsonl`: 100 questions with answers.
- `data/questions/eval_hidden.jsonl`: 50 questions without answers.

Their answers are defined **over the corpus**, not over the real world. Where
a current Wikipedia article disagrees with `corpus.jsonl`, the corpus wins.

`eval_hidden.jsonl` has no gold answers, so a run over it reports tokens,
latency and traces but no accuracy. `GET /datasets` lists it like any other
question set, and it can be run from the Dashboard's Run benchmark tab or with
`python -m ogr.cli batch`. An identical copy sits at
`acceptance/holdout/eval_hidden.jsonl`, which `make reproduce` uses for its
one-time `holdout` step. A CI grep allows only
`backend/src/ogr/eval/batch_runner.py` to name that path in source.

## Embedding and reranking models

The selectable embedding models (`backend/src/ogr/common/embedding_models.py`)
are downloaded from Hugging Face and run locally, or called on Cloudflare
Workers AI where noted. Each keeps the licence published on its model card.
Check the card before redistributing weights or embeddings.

| Model | Hugging Face id | Licence (model card) |
|---|---|---|
| Qwen3-Embedding-0.6B | `Qwen/Qwen3-Embedding-0.6B` | Apache-2.0 |
| EmbeddingGemma-300M | `google/embeddinggemma-300m` | Gemma Terms of Use (gated; accept the terms on Hugging Face to download) |
| gte-large-en-v1.5 | `Alibaba-NLP/gte-large-en-v1.5` | Apache-2.0 |
| mxbai-embed-large-v1 | `mixedbread-ai/mxbai-embed-large-v1` | Apache-2.0 |
| bge-large-en-v1.5 | `BAAI/bge-large-en-v1.5` | MIT (also served as `@cf/baai/bge-large-en-v1.5` on Workers AI) |

The Agentic pipeline's reranker is `@cf/baai/bge-reranker-base` on Cloudflare
Workers AI (`BAAI/bge-reranker-base`, MIT). Calls to Workers AI also fall
under Cloudflare's terms of service.

## Software

Third-party dependencies are declared in `backend/pyproject.toml` and
`frontend/package.json`. Each keeps its own licence. Notable ones: LangChain
and LangGraph (MIT), FastAPI (MIT), pyTigerGraph (Apache-2.0),
sentence-transformers (Apache-2.0), React (MIT), React Router (MIT) and Vite
(MIT).
