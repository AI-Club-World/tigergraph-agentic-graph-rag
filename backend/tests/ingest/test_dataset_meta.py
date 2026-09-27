"""Dataset display names: given > declared > inferred > file name."""

from __future__ import annotations

import json
from collections import Counter

from ogr.ingest import dataset_meta


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")
    return path


def test_infers_source_topic_and_years_from_titles():
    titles = [
        "Sailing at the 2016 Summer Olympics", "Rowing at the 2012 Summer Olympics",
        "Athletics at the 1996 Summer Olympics – Men's 1500 metres", "Heat (film)",
    ]
    hosts = Counter({"en.wikipedia.org": 4})
    assert dataset_meta.infer_title(titles, hosts, 4) == "Wikipedia · Summer Olympics · 1996–2016"


def test_nothing_shared_infers_nothing():
    assert dataset_meta.infer_title(["Alpha", "Beta", "Gamma", "Delta"], Counter(), 4) is None


def test_resolution_order(tmp_path):
    corpus = _write(tmp_path / "corpus.jsonl", [
        {"doc_id": "1", "text": "t", "title": "Heat (film)", "dataset": "Film reviews"},
        {"doc_id": "2", "text": "t", "title": "Up (film)", "dataset": "Film reviews"},
    ])
    assert dataset_meta.describe(corpus)["title"] == "Film reviews"
    assert dataset_meta.describe(corpus)["title_source"] == "declared"
    dataset_meta.write_meta(corpus, title="My films")
    assert dataset_meta.describe(corpus)["title"] == "My films"

    bare = _write(tmp_path / "bare.jsonl", [{"doc_id": "1", "text": "t"}])
    assert dataset_meta.describe(bare) == {
        "title": "bare", "title_source": "file", "documents": 1, "description": None, "source_file": None,
    }


def test_a_changed_file_is_scanned_again(tmp_path):
    corpus = _write(tmp_path / "c.jsonl", [{"doc_id": "1", "text": "t"}])
    assert dataset_meta.describe(corpus)["documents"] == 1
    _write(corpus, [{"doc_id": "1", "text": "t"}, {"doc_id": "2", "text": "more"}])
    assert dataset_meta.describe(corpus)["documents"] == 2
