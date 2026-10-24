"""Ask back on an ambiguous venue day (backlog item 1).

A venue can host several events on one day. When the question names no
event and those events give different answers, the agent asks which one was
meant (stop_reason disambiguation_required, candidates named) instead of
answering from whichever row came back first."""

from __future__ import annotations

from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.pipelines.p3_agentic.agents.entity_linking import (
    EntityLinker,
    ResolvedAnchors,
    ambiguous_events,
    event_label,
    narrow_to_named,
)
from ogr.pipelines.p3_agentic.agents.multi_hop import run_venue_events
from ogr.pipelines.p3_agentic.intent import IntentSchema
from tests.pipelines.p3.test_orchestrator import _make_mock_llm

DAY = dict(date_year=2016, date_month=8, date_day_start=6)


def _row(event_id, name, gold, date_text="6 August"):
    return {
        "event_id": event_id, "event_name": name, "title": f"Fencing at the 2016 Summer Olympics – {name}",
        "doc_id": f"Q{event_id}", "date_text": date_text, "date_year": 2016, "date_month": 8,
        "date_day_start": 6, "date_day_end": None, "gold": gold, "value": gold,
    }


SABRE = _row("fencing-2016-Summer-men-s-sabre", "Men's sabre", "Áron Szilágyi")
EPEE = _row("fencing-2016-Summer-women-s-epee", "Women's épée", "Emese Szász")


class TestAmbiguousEvents:
    def test_events_that_give_different_answers_are_the_candidates(self):
        anchors = ResolvedAnchors(venue="Carioca Arena 3", **DAY)
        assert ambiguous_events([SABRE, EPEE], anchors, "gold") == [SABRE, EPEE]

    def test_events_that_agree_on_the_answer_need_no_question(self):
        same = dict(EPEE, gold=SABRE["gold"], value=SABRE["value"])
        assert ambiguous_events([SABRE, same], ResolvedAnchors(**DAY), "gold") == []

    def test_one_event_or_several_rows_of_one_event_need_no_question(self):
        assert ambiguous_events([SABRE], ResolvedAnchors(**DAY), "gold") == []
        assert ambiguous_events([SABRE, dict(SABRE, value="x")], ResolvedAnchors(**DAY), "gold") == []

    def test_asking_which_events_were_held_is_answered_by_all_of_them(self):
        assert ambiguous_events([SABRE, EPEE], ResolvedAnchors(**DAY), "event_name") == []

    def test_only_a_venue_day_question_is_asked_back(self):
        assert ambiguous_events([SABRE, EPEE], ResolvedAnchors(date_year=2016), "gold") == []
        assert ambiguous_events([SABRE, EPEE], ResolvedAnchors(title="Men's sabre", **DAY), "gold") == []

    def test_events_kept_only_because_none_covers_the_day_are_not_candidates(self):
        other_days = [dict(SABRE, date_day_start=9), dict(EPEE, date_day_start=10)]
        assert ambiguous_events(other_days, ResolvedAnchors(**DAY), "gold") == []

    def test_an_unknown_target_field_still_depends_on_the_event(self):
        rows = [dict(SABRE, value=""), dict(EPEE, value="")]
        assert ambiguous_events(rows, ResolvedAnchors(**DAY), "winner") == rows

    def test_a_candidate_is_named_by_its_page_title_and_date(self):
        assert event_label(SABRE) == "Fencing at the 2016 Summer Olympics – Men's sabre (6 August)"
        assert event_label({"event_id": "e1"}) == "e1"


class TestNarrowToNamed:
    def test_the_event_the_question_names_is_kept(self):
        anchors = ResolvedAnchors(question="Who won the women's épée held at Carioca Arena 3 on 6 August 2016?")
        assert narrow_to_named([SABRE, EPEE], anchors) == [EPEE]

    def test_the_longest_stated_name_wins(self):
        rows = [_row("a", "Singles", "x"), _row("b", "Women's singles", "y")]
        anchors = ResolvedAnchors(question="Who won the women's singles on 6 August?")
        assert [r["event_id"] for r in narrow_to_named(rows, anchors)] == ["b"]

    def test_a_name_inside_a_longer_word_does_not_match(self):
        anchors = ResolvedAnchors(question="Who won the women's sabre?")
        assert narrow_to_named([SABRE, EPEE], anchors) == [SABRE, EPEE]  # "men's sabre" ≠ "women's sabre"


class _VenueClient:
    """A venue with two events on 6 August 2016."""

    ROWS = {SABRE["event_id"]: SABRE, EPEE["event_id"]: EPEE}

    def _run_query(self, name, params):
        if name == "q4_traverse":
            return [{"event_id": e} for e in self.ROWS]
        if name == "q1_lookup":
            row = self.ROWS.get(params.get("event_id"))
            return [{k: v for k, v in row.items() if k != "value"}] if row else []
        return []


def test_venue_expansion_names_the_candidates_when_the_answer_depends_on_the_event():
    anchors = ResolvedAnchors(venue="Carioca Arena 3", games="2016-Summer",
                              question="Who won gold at Carioca Arena 3 on 6 August 2016?", **DAY)
    result = run_venue_events(_VenueClient(), IntentSchema(operation="TRAVERSE", target_field="gold"), anchors)
    assert result.ask_back == [event_label(SABRE), event_label(EPEE)]
    assert "asking which one" in result.notes


def test_venue_expansion_does_not_ask_when_the_question_names_the_event():
    anchors = ResolvedAnchors(venue="Carioca Arena 3", games="2016-Summer",
                              question="Who won the men's sabre at Carioca Arena 3 on 6 August 2016?", **DAY)
    result = run_venue_events(_VenueClient(), IntentSchema(operation="TRAVERSE", target_field="gold"), anchors)
    assert result.ask_back == []
    assert [r["event_id"] for r in result.evidence] == [SABRE["event_id"]]


def _run(question: str):
    from ogr.pipelines.p3_agentic.orchestrator import run_p3_agentic

    model = _make_mock_llm(answer="Áron Szilágyi")
    intent = MagicMock()
    intent.content = '{"operation": "TRAVERSE", "anchor": {}, "target_field": "gold"}'
    intent.tool_calls = []
    intent.usage_metadata = {"input_tokens": 40, "output_tokens": 10, "total_tokens": 50}
    intent.response_metadata = {}
    answer = model.invoke.return_value
    model.invoke.side_effect = [intent] + [answer] * 10
    linker = EntityLinker(games_vocab=["2016-Summer"], sports_vocab=["Fencing"],
                          venues_vocab=["Carioca Arena 3", "Carioca Arena 1"])
    record = run_p3_agentic(question, llm_model=model, tg_client=_VenueClient(), entity_linker=linker,
                            config=RunConfig(llm_supports_tool_calling="false"))
    return record, model


class TestOrchestratorAsksBack:
    def test_an_ambiguous_venue_day_ends_with_the_candidates(self):
        record, model = _run("Who won gold in the event held at Carioca Arena 3 on 6 August 2016?")
        assert record.status == "done"
        assert record.stop_reason == "disambiguation_required"
        assert record.candidates == [event_label(SABRE), event_label(EPEE)]
        assert record.answer.startswith("Which event did you mean:")
        assert "Men's sabre" in record.answer and "Women's épée" in record.answer
        assert model.invoke.call_count == 1  # the intent parse only: nothing was guessed
        assert record.tokens.total == 50
        assert sum(step.tokens.total for step in record.trace) == record.tokens.total
        assert any("asking which one" in step.notes for step in record.trace)

    def test_naming_the_event_answers_it(self):
        record, model = _run("Who won gold in the men's sabre held at Carioca Arena 3 on 6 August 2016?")
        assert record.stop_reason != "disambiguation_required"
        assert record.candidates is None
        assert model.invoke.call_count >= 2
