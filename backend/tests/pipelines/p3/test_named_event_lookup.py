"""Q1 on a named event: exact derived event_id first, then title (pub-052)."""

from __future__ import annotations

from unittest.mock import MagicMock

from ogr.ingest.infobox import event_id_from_parts
from ogr.pipelines.p3_agentic.agents.entity_linking import ResolvedAnchors, lookup_named_event


def test_event_id_matches_ingest_for_an_event_name_or_a_page_title():
    expected = "biathlon-2022-Winter-women-s-relay"
    assert event_id_from_parts("Biathlon", "2022-Winter", "Women's relay") == expected
    assert event_id_from_parts(
        "Biathlon", "2022-Winter", "Biathlon at the 2022 Winter Olympics – Women's relay"
    ) == expected
    assert event_id_from_parts("Weightlifting", "2016-Summer", "Men's +105 kg").endswith("men-s-plus-105-kg")


def test_derived_id_needs_sport_games_and_title_and_never_overrides_a_given_id():
    assert ResolvedAnchors(sport="Biathlon", games="2022-Winter", title="Women's relay").derived_event_id
    assert ResolvedAnchors(sport="Biathlon", title="Women's relay").derived_event_id is None
    assert ResolvedAnchors(
        sport="Biathlon", games="2022-Winter", title="Women's relay", event_id="x"
    ).derived_event_id is None


def test_the_derived_id_is_tried_first():
    client = MagicMock()
    client._run_query.return_value = [{"event_id": "biathlon-2022-Winter-women-s-relay", "nations": 20}]
    anchors = ResolvedAnchors(sport="Biathlon", games="2022-Winter", title="Women's relay")
    assert lookup_named_event(client, anchors, "nations")[0]["nations"] == 20
    client._run_query.assert_called_once_with(
        "q1_lookup", {"title": "", "event_id": "biathlon-2022-Winter-women-s-relay", "target_field": "nations"}
    )


def test_an_unknown_derived_id_falls_back_to_the_title_narrowed_to_the_games():
    rows = [
        {"event_id": "biathlon-2018-Winter-women-s-relay", "date_year": 2018},
        {"event_id": "biathlon-2022-Winter-women-s-relay", "date_year": 2022},
    ]
    client = MagicMock()
    client._run_query.side_effect = [[], rows]
    anchors = ResolvedAnchors(sport="Biathlon", games="2022-Winter", title="Women's relay")
    assert lookup_named_event(client, anchors) == [rows[1]]
    assert client._run_query.call_args.args[1]["title"] == "Women's relay"
