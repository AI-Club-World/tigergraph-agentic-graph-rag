"""Injection harness (ROUND2-DESIGN.md §8). Needs the Round-1 corpus."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ogr.datasets.block_records import BlockRecordAdapter
from ogr.datasets.base import SourceRecord
from ogr.eval.batch_runner import load_questions
from ogr.harness.generate import HarnessConfig, generate, write_output
from ogr.harness.templates import PROSE
from ogr.pipelines.temporal import detect_temporal_scope

CORPUS = Path(__file__).resolve().parents[3] / "data" / "corpus" / "corpus.jsonl"
pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="data/corpus/corpus.jsonl not present")


@pytest.fixture(scope="module")
def out():
    return generate(CORPUS, HarnessConfig(n_per_subset=30, difficulty=3))


def test_deterministic_for_a_config(out):
    again = generate(CORPUS, HarnessConfig(n_per_subset=30, difficulty=3))
    assert again.records == out.records and again.questions == out.questions
    other = generate(CORPUS, HarnessConfig(n_per_subset=30, difficulty=3, seed=7))
    assert other.questions != out.questions


def test_every_subset_is_filled_and_split_by_event(out):
    assert out.manifest["questions"] == {"evolving": 30, "conflicting": 30, "uncertain": 30}
    by_event: dict[str, set[str]] = {}
    for q in out.questions:
        by_event.setdefault(q["harness"]["event_id"], set()).add(q["split"])
    assert all(len(splits) == 1 for splits in by_event.values())
    assert {q["split"] for q in out.questions} == {"dev", "test"}


def test_each_question_parses_to_the_scope_its_ground_truth_assumes(out):
    for q in out.questions:
        assert detect_temporal_scope(q["question"]).mode == q["harness"]["scope"], q["question"]


def test_no_record_accuses_a_real_person(out):
    """Events and names are real; generated statements are neutral revisions."""
    banned = re.compile(r"doping|disqualif|stripped|cheat|banned|suspended|positive test", re.I)
    assert not [r["doc_id"] for r in out.records if banned.search(r["text"])]
    assert all(r["synthetic"] for r in out.records)


def test_every_answer_is_stated_in_a_gold_document(out):
    texts = {r["doc_id"]: r["text"] for r in out.records}
    for q in out.questions:
        injected = [d for d in q["gold_doc_ids"] if d in texts]
        if not injected:
            continue  # stated by the Round-1 page
        assert any(q["answer"][-1] in texts[d] for d in injected), q["qid"]


def test_an_unanswerable_item_states_its_truth_nowhere(out):
    """A lone hedged rumour that is wrong: no pipeline can find the true value."""
    texts = " ".join(r["text"] for r in out.records)
    unanswerable = [q for q in out.questions if q["harness"].get("answerable") is False]
    assert unanswerable
    for q in unanswerable:
        assert not any(variant in texts for variant in q["answer"] if len(variant) >= 4), q["qid"]


def test_rumours_never_state_the_truth(out):
    rumours = [q for q in out.questions if q["harness"].get("rumour")]
    assert rumours
    assert all(q["harness"]["rumour"] not in q["answer"] for q in rumours)


def test_claims_do_not_depend_on_the_prose_template(out):
    """Overfitting guard (§8.4): every template family yields the same claims."""
    adapter = BlockRecordAdapter("r2-injected")
    record = next(r for r in out.records if "attendance:" in r["text"] and "about" not in r["text"])
    head, _, _ = record["text"].partition("Source:")
    seen = set()
    for kind in ("attendance", "attendance_hedged"):
        for template in PROSE[kind]:
            prose = template.format(event="final", value="1,000", old="A", new="B")
            doc: SourceRecord = adapter.document({**record, "text": head + "Source: x.\n\n" + prose})
            [claim] = [c for c in adapter.claims(doc) if c.predicate == "attendance"]
            seen.add((claim.predicate, claim.value_text))
    assert len(seen) == 1


def test_output_files_load_as_an_eval_set(out, tmp_path):
    paths = write_output(out, tmp_path)
    dry = load_questions(paths["dryrun"])
    assert len(dry) == 10 and {q.qtype for q in dry} == {"evolving", "conflicting", "uncertain"}
    assert len(load_questions(paths["dev"])) + len(load_questions(paths["test"])) == 90
    questions = load_questions(paths["questions"])
    assert len(questions) == 90 and {q.qtype for q in questions} == {"evolving", "conflicting", "uncertain"}
    assert all(q.answer for q in questions)
    adapter = BlockRecordAdapter("r2-injected")
    docs = list(adapter.documents(paths["corpus"]))
    assert len(docs) == out.manifest["records"]
    assert all(list(adapter.claims(d)) for d in docs)


def test_fitted_weights_load_into_the_agent(out, tmp_path, monkeypatch):
    import json
    from dataclasses import asdict

    from ogr.pipelines.p3_agentic.agents.claims import load_weights
    from ogr.reasoning.resolve import Weights

    path = tmp_path / "w.json"
    path.write_text(json.dumps(asdict(Weights(reliability=2.0, platt_b=1.5))), encoding="utf-8")
    monkeypatch.setenv("OGR_ROUND2_WEIGHTS", str(path))
    assert load_weights() == Weights(reliability=2.0, platt_b=1.5)
    monkeypatch.setenv("OGR_ROUND2_WEIGHTS", str(tmp_path / "missing.json"))
    assert load_weights() == Weights()

