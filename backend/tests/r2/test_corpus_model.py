"""Corpus model: numbers, publication times, authority classes, REPORTS_ON links."""

from __future__ import annotations

import collections

import pytest

from ogr.r2.corpus_model import (
    AUTHORITY_LEXICON,
    classify_authority,
    parse_number,
    parse_published,
)
from tests.r2.conftest import needs_corpus


class TestNumbers:
    @pytest.mark.parametrize("raw,expected", [
        ("24", (24.0, "")),
        ("1,234", (1234.0, "")),
        ("1988", (1988.0, "year")),
        ("$32 million", (32e6, "USD")),
        ("$1.2 billion", (1.2e9, "USD")),
        ("£10 million", (10e6, "GBP")),
        ("€14 million", (14e6, "EUR")),
        ("HK$20 million", (20e6, "HKD")),
        ("$55million", (55e6, "USD")),
        ("$400,000", (400000.0, "USD")),
        ("15 crore", (15e7, "crore")),
        ("142 minutes", (142.0, "minutes")),
        ("51.26 billion (2025)", (51.26e9, "")),
    ])
    def test_clean_values_parse(self, raw, expected):
        assert parse_number(raw) == expected

    @pytest.mark.parametrize("raw", [
        "$60–70 million", "$15-20 million", "₹10-12 crores", "Ron Howard", "1984-03-09", "", "about 40",
        "$482.3millionThis is the cumulative gross",
    ])
    def test_ranges_dates_and_prose_stay_text(self, raw):
        assert parse_number(raw) == (None, "")


class TestPublished:
    def test_iso_with_offset_keeps_the_stated_offset(self):
        assert parse_published("2028-07-23 22:15 PDT (UTC−07:00)") == "2028-07-23T22:15:00-07:00"
        assert parse_published("2029-01-20 10:00 CET (UTC+01:00)") == "2029-01-20T10:00:00+01:00"

    def test_no_stamp_is_empty(self):
        assert parse_published("sometime in July") == ""


class TestMiniModel:
    def test_events_athletes_and_won_edges(self, mini_model):
        by_id = {e.doc_id: e for e in mini_model.events}
        assert len(mini_model.events) == 11
        assert by_id["L1"].synthetic and not by_id["E1"].synthetic
        assert (by_id["E1"].sport, by_id["E1"].year, by_id["E1"].season) == ("Athletics", 2012, "Summer")
        assert "ann alpha" in mini_model.athletes and mini_model.athletes["ann alpha"].name == "Ann Alpha"
        medals = [(m.medal, m.name, m.noc, m.place) for m in by_id["J2"].medallists]
        assert ("gold", "Dan Delta", "FRA", 1) in medals and ("gold", "Eva Echo", "FRA", 1) in medals
        assert ("bronze", "Pia Omicron", "BRA", 2) in medals
        assert len(mini_model.won) == sum(len(e.medallists) for e in mini_model.events)

    def test_entities_and_facts_include_keys_the_round1_parser_stops_at(self, mini_model):
        assert {e.name for e in mini_model.entities} == {"Splash (film)", "Cocoon (film)", "Jane Governor"}
        facts = {(f.entity_id, f.predicate): f for f in mini_model.facts}
        assert facts[("ent:F1", "budget")].value_num == 8e6 and facts[("ent:F1", "budget")].note == "USD"
        assert facts[("ent:F1", "director")].value_num is None
        # "jr/sr" would have ended the Round-1 field block; the numbered keys after it survive.
        assert facts[("ent:P1", "predecessor1")].value_text == "Old Gov"
        assert facts[("ent:P1", "successor1")].value_text == "New Gov"
        assert facts[("ent:P1", "term_start1")].claim_id == "ent:P1:term_start1"

    def test_source_records(self, mini_model):
        by_id = {s.doc_id: s for s in mini_model.sources}
        assert set(by_id) == {"SYN-A", "SYN-B"}
        a = by_id["SYN-A"]
        assert (a.source_name, a.published_at, a.authority) == (
            "Venue scoreboard operator", "2028-07-23T21:09:00-07:00", "operational")
        assert a.published_text.startswith("2028-07-23 21:09 PDT")
        assert a.text.startswith("Women's individual archery")
        assert by_id["SYN-B"].authority == "official"

    def test_reports_on_links_name_with_sport_or_venue(self, mini_model):
        links = {(k.record_id, k.event_id): k.score for k in mini_model.links}
        assert links[("SYN-A", "archery-2028-Summer-women-s-individual")] == 1.0
        # The record never names the men's event, so it is not linked to it.
        assert ("SYN-A", "archery-2028-Summer-men-s-individual") not in links
        # SYN-B names no event: linked through the medallist it names, at the lower score.
        assert links[("SYN-B", "archery-2028-Summer-men-s-individual")] == 0.5

    def test_chunks_cover_every_document_without_embeddings(self, mini_model):
        assert {c.doc_id for c in mini_model.chunks} == {d.doc_id for d in mini_model.documents}
        assert all(not c.embedding for c in mini_model.chunks)


class TestAuthorityLexicon:
    def test_lexicon_is_ordered_and_names_the_four_classes(self):
        assert [label for label, _ in AUTHORITY_LEXICON] == ["official", "unreliable", "operational", "secondary"]

    @pytest.mark.parametrize("source,label", [
        ("LA28 shooting jury (signed certificate)", "official"),
        ("Westside Pavilion control desk (signed clock log)", "official"),
        ("LA28 competition director (binding safety bulletin)", "official"),
        ("Third-party medal data feed (legacy format)", "unreliable"),
        ("LA28 ticketing (automated email)", "unreliable"),
        ("Venue scoreboard operator", "operational"),
        ("World archery federation (registration database)", "operational"),
        ("Local sports bulletin", "secondary"),
        ("Range Report (sports newsletter)", "secondary"),
        ("Something unheard of", "unclassified"),
    ])
    def test_classification(self, source, label):
        assert classify_authority(source) == label


@needs_corpus
class TestRealSourceRecords:
    def test_exactly_39_records_each_with_source_time_and_a_class(self, real_model):
        assert len(real_model.sources) == 39
        for s in real_model.sources:
            assert s.source_name and s.published_text and s.text, s.doc_id
            assert s.published_at.count("T") == 1 and s.published_at[-6] in "+-", s.doc_id
            assert s.authority in {"official", "operational", "secondary", "unreliable"}, (s.doc_id, s.source_name)

    def test_class_counts_and_known_cases(self, real_model):
        by_id = {s.doc_id: s.authority for s in real_model.sources}
        assert collections.Counter(by_id.values()) == {
            "official": 13, "unreliable": 11, "operational": 10, "secondary": 5}
        assert by_id["SYN-LA28-S031"] == "official"      # photo-finish jury, signed result
        assert by_id["SYN-LA28-S016"] == "unreliable"    # spectator blog
        assert by_id["SYN-LA28-S011"] == "operational"   # scoreboard operator
        assert by_id["SYN-LA28-S022"] == "secondary"     # headline roundup

    def test_published_time_of_the_photo_finish_decision(self, real_model):
        s = next(s for s in real_model.sources if s.doc_id == "SYN-LA28-S031")
        assert s.published_at == "2028-07-23T22:15:00-07:00"
        assert s.published_text.startswith("2028-07-23 22:15 PDT")

    def test_link_statistics(self, real_model):
        per = collections.Counter(link.record_id for link in real_model.links)
        counts = [per.get(s.doc_id, 0) for s in real_model.sources]
        assert collections.Counter(counts) == {1: 30, 2: 9}  # no record links to nothing
        # The nine two-event records are genuinely ambiguous: both men's and women's
        # individual archery, the 10 m air pistol and 25 m pistol bulletins, and
        # "men's singles" at a venue shared by badminton and table tennis.
        two = {s.doc_id for s, n in zip(real_model.sources, counts, strict=True) if n == 2}
        assert two == {f"SYN-LA28-S{n:03d}" for n in (2, 7, 13, 14, 20, 24, 26, 32, 35)}

    def test_decisive_records_link_to_their_event(self, real_model):
        events = real_model.event_by_id()

        def linked(doc_id):
            return {events[k.event_id].event_name for k in real_model.links
                    if k.record_id == doc_id and k.score == 1.0}
        assert linked("SYN-LA28-S031") == {"Men's 100 metres"}
        assert linked("SYN-LA28-S030") == {"Women's Omnium"}
        assert linked("SYN-LA28-S004") == {"Women's 10 metre air pistol"}
        assert linked("SYN-LA28-S028") == {"Women's individual"}
