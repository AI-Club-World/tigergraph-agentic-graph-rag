"""Supersession, contradiction, reliability, resolution and calibration (ROUND2-DESIGN.md §2, §4)."""

from __future__ import annotations

import math

import pytest

from ogr.datasets.base import ClaimRecord, claim_id
from ogr.eval.calibration import brier, expected_calibration_error, fit_platt, reliability_table
from ogr.pipelines.temporal import TemporalScope
from ogr.reasoning.relations import build_relations
from ogr.reasoning.reliability import estimate_reliability
from ogr.reasoning.resolve import Weights, resolve

EVENT = "athletics-2012-Summer-men-s-800-metres"


def claim(value, source, observed=None, *, revision=False, hedged=False, valid_from=None, num=None, conf=1.0):
    return ClaimRecord(
        claim_id=claim_id(source, value, observed, revision), doc_id=f"d-{source}-{observed}",
        dataset_id="t", subject_id=EVENT, subject_name="800 m", predicate="gold",
        value_text=value, value_num=num, valid_from=valid_from, observed_at=observed, source_id=source,
        extraction_conf=conf, hedged=hedged, hedge_terms=["reportedly"] if hedged else [], revision=revision,
    )


ORIGINAL = claim("Runner A", "src:wiki", None, valid_from="2012-08-09")
REALLOC = claim("Runner B", "src:ioc", "2016-11-02", revision=True, valid_from="2016-10-30")


class TestRelations:
    def test_a_dated_revision_supersedes_the_undated_page(self):
        [rel] = build_relations([ORIGINAL, REALLOC])
        assert (rel.kind, rel.src, rel.dst) == ("SUPERSEDES", REALLOC.claim_id, ORIGINAL.claim_id)
        assert "revision" in rel.reason

    def test_a_later_statement_from_another_source_without_a_revision_cue_contradicts(self):
        other = claim("Runner C", "src:blog", "2017-01-01")
        kinds = sorted(r.kind for r in build_relations([ORIGINAL, other]))
        assert kinds == ["CONTRADICTS"]

    def test_the_same_source_restating_later_supersedes(self):
        old = claim("Runner A", "src:feed", "2012-08-09")
        new = claim("Runner B", "src:feed", "2012-08-10")
        [rel] = build_relations([old, new])
        assert rel.kind == "SUPERSEDES" and rel.reason.startswith("same source")

    def test_a_hedged_revision_rumour_does_not_supersede_the_result(self):
        rumour = claim("Runner C", "src:blog", "2018-01-01", revision=True, hedged=True)
        r = resolve([ORIGINAL, rumour], TemporalScope("latest"), reliability={"src:wiki": 0.8, "src:blog": 0.3})
        assert r.chosen.value == "Runner A" and not r.superseded

    def test_a_hedged_restatement_does_not_supersede_a_firm_one(self):
        firm = claim("25,210", "src:feed", "2017-04-12", num=25210.0)
        hedged = claim("about 24,600", "src:feed", "2017-05-05", num=24600.0, hedged=True)
        assert [r.kind for r in build_relations([firm, hedged])] == ["CONTRADICTS"]
        assert resolve([firm, hedged]).chosen.value == "25210"

    def test_the_same_value_is_corroboration_not_a_relation(self):
        assert build_relations([claim("Runner A", "src:a"), claim("runner a", "src:b", "2014-01-01")]) == []

    def test_disjoint_validity_is_not_a_contradiction(self):
        a = ClaimRecord(**{**claim("X", "src:a").__dict__, "valid_from": "2000-01-01", "valid_to": "2004-12-31"})
        b = ClaimRecord(**{**claim("Y", "src:b").__dict__, "claim_id": "y", "valid_from": "2005-01-01"})
        assert build_relations([a, b]) == []


class TestReliability:
    def test_sources_that_agree_with_the_majority_gain_reliability(self):
        claims = []
        for i in range(5):
            subject = f"e{i}"
            for src in ("src:good1", "src:good2"):
                claims.append(ClaimRecord(**{**claim("True", src).__dict__, "claim_id": f"{src}{i}", "subject_id": subject}))
            claims.append(ClaimRecord(**{**claim(f"Wrong{i}", "src:bad").__dict__, "claim_id": f"bad{i}", "subject_id": subject}))
        rel = estimate_reliability(claims)
        assert rel["src:good1"] > rel["src:bad"] and rel["src:good2"] > rel["src:bad"]

    def test_a_prior_is_kept_in_the_estimate(self):
        rel = estimate_reliability([claim("A", "src:x")], priors={"src:x": 0.9})
        assert rel["src:x"] == pytest.approx(0.9, abs=0.01)


class TestResolve:
    def test_latest_takes_the_revision_and_keeps_the_original_as_superseded(self):
        r = resolve([ORIGINAL, REALLOC], TemporalScope("latest"))
        assert r.chosen.value == "Runner B"
        assert [c.value_text for c in r.superseded] == ["Runner A"]
        assert r.conflicted and 0 < r.confidence <= 1

    def test_original_takes_the_first_statement(self):
        r = resolve([ORIGINAL, REALLOC], TemporalScope("original"))
        assert r.chosen.value == "Runner A"

    def test_as_of_a_date_before_the_revision_takes_what_was_known_then(self):
        r = resolve([ORIGINAL, REALLOC], TemporalScope("as_of", "2015-12-31"))
        assert r.chosen.value == "Runner A" and [c.value_text for c in r.out_of_scope] == ["Runner B"]

    def test_corroborated_reliable_value_beats_a_lone_unreliable_one(self):
        claims = [claim("True", "src:a", "2020-01-01"), claim("True", "src:b", "2020-01-02"),
                  claim("Wrong", "src:c", "2020-01-03")]
        r = resolve(claims, reliability={"src:a": 0.9, "src:b": 0.8, "src:c": 0.3})
        assert r.chosen.value == "True" and [a.value for a in r.alternatives] == ["Wrong"]
        assert r.chosen.probability > 0.5

    def test_a_lone_hedged_claim_is_not_certain(self):
        r = resolve([claim("Maybe", "src:blog", "2020-01-01", hedged=True)], reliability={"src:blog": 0.4})
        assert r.chosen.value == "Maybe" and r.confidence < 0.5

    def test_two_reliable_unhedged_sources_are_confident(self):
        r = resolve([claim("Sure", "src:a"), claim("Sure", "src:b")], reliability={"src:a": 0.95, "src:b": 0.9})
        assert r.confidence > 0.9

    def test_resolution_is_deterministic_and_inspectable(self):
        claims = [claim("X", "src:a", "2020-01-01"), claim("Y", "src:b", "2020-01-01")]
        first, second = resolve(claims), resolve(list(reversed(claims)))
        assert first.chosen.value == second.chosen.value
        d = first.to_dict()
        assert set(d["chosen"]["terms"]) == {"reliability", "corroboration", "recency", "extraction", "hedged_share"}

    def test_a_number_is_answered_without_its_qualifier(self):
        r = resolve([claim("about 17,140", "src:a", num=17140.0, hedged=True)])
        assert r.chosen.value == "17140"

    def test_no_claims_resolves_to_nothing(self):
        assert resolve([]).chosen is None


class TestCalibration:
    def test_perfect_and_worst_cases(self):
        assert brier([1.0, 0.0], [1, 0]) == 0.0 and brier([1.0, 0.0], [0, 1]) == 1.0
        assert expected_calibration_error([0.8] * 10, [1] * 8 + [0] * 2) == pytest.approx(0.0)
        assert expected_calibration_error([0.9] * 10, [1] * 5 + [0] * 5) == pytest.approx(0.4)
        assert brier([], []) is None and expected_calibration_error([], []) is None

    def test_reliability_table_bins(self):
        rows = reliability_table([0.05, 0.95, 1.0], [0, 1, 1])
        assert [r["n"] for r in rows] == [1, 2]

    def test_platt_fit_reduces_overconfidence(self):
        conf = [0.95] * 20 + [0.9] * 20
        correct = [1] * 12 + [0] * 8 + [1] * 10 + [0] * 10
        a, b = fit_platt(conf, correct)
        fitted = [1 / (1 + math.exp(-(a * math.log(p / (1 - p)) + b))) for p in conf]
        assert expected_calibration_error(fitted, correct) < expected_calibration_error(conf, correct)
        assert fit_platt([], []) == (1.0, 0.0)
        a, b = fit_platt([0.6] * 20, [1] * 20)  # no errors: confident, not certain
        p = 1 / (1 + math.exp(-(a * math.log(0.6 / 0.4) + b)))
        assert 0.8 < p < 1.0

    def test_weights_carry_the_platt_parameters(self):
        r = resolve([claim("A", "src:a")], weights=Weights(platt_a=0.0, platt_b=0.0))
        assert r.confidence == pytest.approx(0.5)
