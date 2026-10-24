"""Temporal scope detection (Round 2, ROUND2-DESIGN.md §3.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ogr.pipelines.temporal import detect_temporal_scope

ROOT = Path(__file__).resolve().parents[3]
ROUND1_SETS = [
    ROOT / "data" / "questions" / "eval_public.jsonl",
    ROOT / "data" / "questions" / "eval_hidden.jsonl",
    ROOT / "acceptance" / "paraphrase" / "paraphrase_set.jsonl",
]


@pytest.mark.parametrize(
    ("question", "mode", "t1", "t2"),
    [
        ("Who held the gold medal as of 2015?", "as_of", "2015-12-31", None),
        ("As of 3 March 2019, who was listed as the winner?", "as_of", "2019-03-03", None),
        ("Who was the winner as of August 2017?", "as_of", "2017-08-31", None),
        ("Who was reported as champion before 2016?", "before", "2016-01-01", None),
        ("Who was the officially recorded winner after 2019?", "after", "2019-12-31", None),
        ("Who has been listed as the winner since 2019?", "after", "2019-01-01", None),
        ("How many competitors were reported between 2012 and 2014?", "between", "2012-01-01", "2014-12-31"),
        ("Who is currently credited with the gold medal?", "latest", None, None),
        ("What is the most recent figure for the number of nations?", "latest", None, None),
        ("Who was originally awarded the silver medal?", "original", None, None),
        ("Who won before the reallocation?", "original", None, None),
    ],
)
def test_scopes(question, mode, t1, t2):
    scope = detect_temporal_scope(question)
    assert (scope.mode, scope.t1, scope.t2) == (mode, t1, t2)
    assert scope.cue and not scope.ambiguous


def test_edition_relative_phrasing_is_not_a_fact_scope():
    """Round-1 TRAVERSE: moving along editions, not asking for a fact as known at a time."""
    for q in (
        "Who won the men's 20 km walk at the Summer Olympics held immediately before 2016?",
        "Which venue hosted the event after 2008?",
        "Who won the gold medal in the event held at Olympic Tennis Centre on 15 to 22 August 2004?",
    ):
        assert detect_temporal_scope(q).mode == "none", q


def test_a_scope_word_without_a_date_is_ambiguous_and_reads_as_latest():
    scope = detect_temporal_scope("Who was the champion as of the closing ceremony?")
    assert scope.mode == "latest" and scope.ambiguous


def test_no_round1_question_is_time_scoped():
    """Regression guard: Round-1 routing must not change. This reads the
    question text only (no answers, no qtype) and asserts the detector stays
    silent; the lexicon is general English, not derived from these sets."""
    scoped = []
    for path in ROUND1_SETS:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            q = json.loads(line)["question"]
            if detect_temporal_scope(q).scoped:
                scoped.append(q)
    assert scoped == []
