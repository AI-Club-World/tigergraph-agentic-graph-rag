"""Dataset adapters (ROUND2-DESIGN.md §1)."""

from __future__ import annotations

import json

import pytest

from ogr.datasets import adapter_for
from ogr.datasets.base import iso_date, normalize_predicate
from ogr.datasets.block_records import BlockRecordAdapter
from ogr.datasets.olympic import OlympicAdapter
from ogr.reasoning.hedges import hedge_terms, revision_terms
from tests.ingest.test_infobox import CANOE

TITLE = "Canoeing at the 2012 Summer Olympics – Men's K-2 1000 metres"


def _write(tmp_path, *records):
    path = tmp_path / "d.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return path


def test_iso_dates_take_the_start_or_end_of_a_period():
    assert iso_date("2018") == "2018-01-01" and iso_date("2018", end=True) == "2018-12-31"
    assert iso_date("August 2016", end=True) == "2016-08-31"
    assert iso_date("6 to 8 August 2012") == "2012-08-06"
    assert iso_date("2019-03-04T10:00:00Z") == "2019-03-04"
    assert iso_date("sometime") is None and iso_date(None) is None


def test_predicates_are_normalised():
    assert normalize_predicate("Winner") == "gold"
    assert normalize_predicate("participants") == "competitors"
    assert normalize_predicate("Gold medallist") == "gold"
    assert normalize_predicate("record_time") == "record_time"


def test_hedges_and_revisions():
    assert hedge_terms("He is reported to have won; figures are provisional, about 30.") == [
        "is reported to", "provisional", "about"]
    assert hedge_terms("He won the final.") == []
    assert revision_terms("The medal was reallocated after he was stripped of it.") == ["reallocated", "stripped"]


class TestOlympicAdapter:
    def test_infobox_fields_become_claims_on_the_event(self, tmp_path):
        adapter = OlympicAdapter("corpus")
        [doc] = adapter.documents(_write(tmp_path, CANOE))
        claims = {c.predicate: c for c in adapter.claims(doc)}
        assert set(claims) >= {"gold", "silver", "bronze", "competitors", "nations", "venue", "date"}
        gold = claims["gold"]
        assert gold.subject_id.startswith("canoeing-2012-Summer-")
        assert gold.source_id == "src:wikipedia.org" and doc.source_class == "encyclopedia"
        assert claims["competitors"].value_num == 24.0
        assert gold.observed_at is None and gold.extraction_conf == 1.0 and not gold.hedged

    def test_a_non_event_page_has_no_claims(self, tmp_path):
        adapter = OlympicAdapter()
        [doc] = adapter.documents(_write(tmp_path, {"doc_id": "Q1", "title": "Film", "text": "A film."}))
        assert list(adapter.claims(doc)) == []


class TestBlockRecords:
    RECORD = {
        "doc_id": "r2-1",
        "title": "Medal reallocated",
        "published_at": "2016-11-02",
        "source": {"id": "src:ioc", "name": "IOC", "class": "official", "reliability": 0.95},
        "text": (
            "[Infobox fact record]\n"
            f"  subject: {TITLE}\n"
            "  gold: Fernando Pimenta\n"
            "  competitors: about 26\n"
            "  valid_from: 2016-10-30\n"
            "  status: correction\n"
            "\n"
            "After a disqualification the gold medal was reallocated to Fernando Pimenta. "
            "Officials say about 26 crews are believed to have started."
        ),
    }

    def test_block_claims_with_provenance_time_and_hedges(self, tmp_path):
        adapter = BlockRecordAdapter("r2")
        [doc] = adapter.documents(_write(tmp_path, self.RECORD))
        assert (doc.source_id, doc.source_class, doc.reliability_prior, doc.published_at) == (
            "src:ioc", "official", 0.95, "2016-11-02")
        claims = {c.predicate: c for c in adapter.claims(doc)}
        assert set(claims) == {"gold", "competitors"}
        gold = claims["gold"]
        assert gold.subject_id == "canoeing-2012-Summer-men-s-k-2-1000-metres"
        assert (gold.valid_from, gold.observed_at, gold.revision) == ("2016-10-30", "2016-11-02", True)
        assert not gold.hedged and gold.extraction_conf == 1.0
        comp = claims["competitors"]
        assert comp.value_num == 26.0 and comp.hedged and comp.extraction_conf == 0.9
        assert comp.hedge_terms == ["about", "are believed to"]

    def test_a_subject_that_is_not_an_event_page_is_a_generic_entity(self, tmp_path):
        record = dict(self.RECORD, text="[Infobox fact record]\n  subject: ACME Corp\n  ceo: Jane Roe\n")
        adapter = BlockRecordAdapter("r2")
        [doc] = adapter.documents(_write(tmp_path, record))
        [claim] = adapter.claims(doc)
        assert (claim.subject_id, claim.predicate, claim.value_text, claim.revision) == (
            "ent:acme-corp", "ceo", "Jane Roe", False)

    def test_a_source_falls_back_to_the_url_host(self, tmp_path):
        record = {"doc_id": "x", "title": "t", "url": "https://www.example.com/a", "text": ""}
        [doc] = BlockRecordAdapter("r2").documents(_write(tmp_path, record))
        assert doc.source_id == "src:example.com" and doc.published_at is None


def test_unknown_adapter_is_refused():
    assert isinstance(adapter_for("olympic", "corpus"), OlympicAdapter)
    with pytest.raises(ValueError):
        adapter_for("nope", "x")
