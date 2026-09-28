"""Answer resolution: an event answered by its short name gets its page title (r2 superlatives)."""

from __future__ import annotations

from ogr.pipelines.p3_agentic.agents.answer_resolution import resolve_answer

MARATHON = "Athletics at the 2008 Summer Olympics – Men's marathon"
ROWS = [
    {"event_id": "e1", "event_name": "Men's marathon", "title": MARATHON, "value": 98,
     "source": "aggregation_argmax"},
    {"event_id": "e2", "event_name": "Men's 50 km walk",
     "title": "Athletics at the 2008 Summer Olympics – Men's 50 kilometres walk", "value": 60,
     "source": "aggregation_argmax"},
]


def test_a_short_event_name_resolves_to_its_page_title():
    r = resolve_answer("Men's marathon", ROWS)
    assert r.answer == MARATHON and r.changed and r.supported


def test_an_unusable_infobox_name_resolves_too():
    rows = [{"event_name": "Fleet/Match", "title": "Sailing at the 2000 Summer Olympics – Soling",
             "source": "aggregation_argmax"}]
    assert resolve_answer("Fleet/Match", rows).answer == "Sailing at the 2000 Summer Olympics – Soling"


def test_the_event_part_of_a_title_matches_when_the_name_differs():
    rows = [{"event_name": "Men's 50 km walk", "title": "Athletics at the 2008 Summer Olympics – Men's 50 kilometres walk",
             "source": "aggregation_argmax"}]
    assert resolve_answer("Men's 50 kilometres walk", rows).changed


def test_an_answer_already_the_title_is_unchanged():
    r = resolve_answer(MARATHON, ROWS)
    assert r.answer == MARATHON and not r.changed


def test_the_same_name_in_several_editions_is_left_as_given():
    rows = [
        {"event_name": "Men's épée", "title": "Fencing at the 2008 Summer Olympics – Men's épée", "source": "graph_traversal"},
        {"event_name": "Men's épée", "title": "Fencing at the 2012 Summer Olympics – Men's épée", "source": "graph_traversal"},
    ]
    r = resolve_answer("Men's épée", rows)
    assert r.answer == "Men's épée" and not r.changed and "2 events" in r.note


def test_other_answers_are_checked_not_changed():
    assert resolve_answer("98", ROWS).supported is True
    unsupported = resolve_answer("Usain Bolt", ROWS)
    assert unsupported.answer == "Usain Bolt" and unsupported.supported is False


def test_prose_only_evidence_has_nothing_to_check_against():
    r = resolve_answer("Men's marathon", [{"text": "Men's marathon ...", "source": "similarity_search"}])
    assert r.supported is None and not r.changed
