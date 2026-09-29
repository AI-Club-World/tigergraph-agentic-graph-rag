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


class TestEvidenceConflicts:
    """Round-2 style: the page's infobox and its prose disagree on a figure."""

    ROW = {"event_id": "e1", "doc_id": "Q9", "title": "Judo at the 2016 Summer Olympics – Women's 57 kg",
           "nations": 23, "competitors": 25, "source": "graph_traversal"}

    def test_a_clean_disagreement_is_reported_with_both_values(self):
        from ogr.pipelines.p3_agentic.agents.answer_resolution import find_conflicts

        prose = {"doc_id": "Q9", "chunk_id": "Q9_c0", "text": "The event drew 24 nations to Rio.",
                 "source": "document_retrieval"}
        assert find_conflicts([self.ROW, prose]) == [
            "nations on Judo at the 2016 Summer Olympics – Women's 57 kg (Q9): infobox 23, page text 24"
        ]
        r = resolve_answer("23", [self.ROW, prose])
        assert r.answer == "23" and r.conflicts and not r.changed  # reported, never changes the answer

    def test_agreement_other_pages_and_several_figures_are_not_conflicts(self):
        from ogr.pipelines.p3_agentic.agents.answer_resolution import find_conflicts

        same = {"doc_id": "Q9", "text": "23 nations and 25 competitors took part."}
        other_page = {"doc_id": "Q10", "text": "40 nations competed."}
        several = {"doc_id": "Q9", "text": "12 athletes in the final, 25 athletes in the heats"}
        assert find_conflicts([self.ROW, same]) == []
        assert find_conflicts([self.ROW, other_page]) == []
        assert find_conflicts([self.ROW, several]) == []

    def test_p3_puts_the_conflict_on_the_verification_step(self):
        from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic
        from tests.graph.test_client_errors import LOOKUP, _model
        from tests.pipelines.test_p2 import _linker
        from ogr.common.config import RunConfig
        from ogr.graph.client import TigerGraphClient

        class Client(TigerGraphClient):
            def __init__(self):
                super().__init__(config=RunConfig(), mock_chunks=[])

            def _run_query(self, name, params):
                return [dict(TestEvidenceConflicts.ROW)]

            def _expand_has_chunk(self, doc_ids):
                return [{"chunk_id": "Q9_c0", "doc_id": "Q9", "text": "24 nations took part.", "seq": 0}]

        record = run_p3_agentic("How many nations competed?", llm_model=_model(LOOKUP, "23"),
                                tg_client=Client(), entity_linker=_linker(),
                                config=RunConfig(llm_supports_tool_calling="false"))
        verify = [s for s in record.trace if s.agent_type == "answer_verification"]
        assert verify, "verification step recorded"
        # The direct lookup shows no prose, so no conflict is claimed without evidence for one.
        assert "conflicting evidence" not in verify[0].notes


def test_infobox_keys_and_years_in_a_chunk_are_not_prose_figures():
    """r5: "competitors: 28 nations: 13" (the infobox serialised in a chunk)
    read as "28 nations"; "2008 competitors:" as a count of 2008."""
    from ogr.pipelines.p3_agentic.agents.answer_resolution import find_conflicts

    row = {"doc_id": "Q1", "title": "T", "nations": 13, "competitors": 28}
    for text in (
        "[Infobox Olympic event] event: x competitors: 28 nations: 13 gold: A",
        "date: 12 August 2008 competitors: 28 nations: 13",
        "28 athletes from 13 nations competed.",
    ):
        assert find_conflicts([row, {"doc_id": "Q1", "text": text}]) == [], text
    assert find_conflicts([row, {"doc_id": "Q1", "text": "The event drew 30 skaters from 14 nations."}]) == [
        "nations on T (Q1): infobox 13, page text 14"
    ]
