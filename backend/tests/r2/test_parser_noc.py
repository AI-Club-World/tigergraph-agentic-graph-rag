"""Parser extension: NOCs aligned with medallist names (silverNOC, bronzeNOC,
numbered tie variants). Round-1 fields are unchanged."""

from __future__ import annotations

from ogr.ingest.infobox import medallist_slots, parse_document, parse_infobox_fields
from tests.r2.conftest import event


def _doc(**kw):
    return parse_document(event("X", "Judo", 2020, "Summer", "Men's 73 kg", **kw))


def test_single_medallists_get_their_noc():
    doc = _doc(gold=[("Jon Kappa", "JPN")], silver=[("Kai Lambda", "GEO")], bronze=[("Lee Mu", "FRA")])
    assert (doc.gold, doc.gold_nocs) == (["Jon Kappa"], ["JPN"])
    assert (doc.silver, doc.silver_noc) == (["Kai Lambda"], ["GEO"])
    assert (doc.bronze, doc.bronze_noc) == (["Lee Mu"], ["FRA"])


def test_a_team_noc_is_repeated_for_every_concatenated_name():
    doc = _doc(gold=[("Rudolf DombiRoland Kokeny", "HUN")])
    assert doc.gold == ["Rudolf Dombi", "Roland Kokeny"] and doc.gold_nocs == ["HUN", "HUN"]


def test_a_third_place_tie_keeps_each_medallists_country():
    doc = _doc(bronze=[("Lee Mu", "JPN"), ("Max NuPia Omicron", "BRA")])
    assert doc.bronze == ["Lee Mu", "Max Nu", "Pia Omicron"]
    assert doc.bronze_noc == ["JPN", "BRA", "BRA"]
    assert len(doc.bronze) == len(doc.bronze_noc)


def test_the_bronze2noc_spelling_is_read_too():
    text = "[Infobox Olympic event]\n  event: Men's foil\n  games: 2028 Summer\n  bronze: A One\n"
    text += "  bronzeNOC: USA\n  bronze2: B Two\n  bronze2NOC: GER\n\nprose\n"
    doc = parse_document({"doc_id": "d", "title": "Fencing at the 2028 Summer Olympics – Men's foil", "text": text})
    assert doc.bronze_noc == ["USA", "GER"]
    assert medallist_slots(parse_infobox_fields(text), "bronze") == [(1, "A One", "USA"), (2, "B Two", "GER")]


def test_a_missing_noc_is_an_empty_string_and_round1_fields_are_unchanged():
    text = "[Infobox Olympic event]\n  event: X\n  games: 2012 Summer\n  gold: Solo Person\n\nprose\n"
    doc = parse_document({"doc_id": "d", "title": "Judo at the 2012 Summer Olympics – X", "text": text})
    assert doc.gold == ["Solo Person"] and doc.gold_nocs == [""] and doc.gold_noc is None
    assert doc.silver_noc == [] and doc.bronze_noc == []


def test_mac_prefix_guard_still_holds_with_nocs():
    doc = _doc(gold=[("Rosannagh MacLennan", "CAN")])
    assert doc.gold == ["Rosannagh MacLennan"] and doc.gold_nocs == ["CAN"]
