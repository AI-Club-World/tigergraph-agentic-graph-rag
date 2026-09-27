"""`verify --pre-build`: a fresh workspace (queries not installed yet) passes,
so `make reproduce` reaches the build that installs them."""

from __future__ import annotations

import ogr.verify as verify
from ogr.common.config import RunConfig


def _stub(monkeypatch, queries):
    monkeypatch.setattr(verify, "check_llm", lambda cfg: ("OK", "llm"))
    monkeypatch.setattr(verify, "check_embedding", lambda cfg: ("OK", "emb"))
    monkeypatch.setattr(verify, "check_tigergraph", lambda cfg: ("OK", "tg"))
    monkeypatch.setattr(verify, "check_queries", lambda cfg: queries)


def test_missing_queries_fail_a_normal_verify_but_not_a_pre_build_one(monkeypatch, capsys):
    _stub(monkeypatch, ("FAIL", "missing: q1_lookup (GRAPH-07 not built yet)"))
    assert verify.run(RunConfig()) == 1
    assert verify.run(RunConfig(), pre_build=True) == 0
    assert "installed by the build" in capsys.readouterr().out


def test_pre_build_still_fails_an_unreachable_graph(monkeypatch):
    _stub(monkeypatch, ("FAIL", "could not list queries: refused"))
    assert verify.run(RunConfig(), pre_build=True) == 1


def test_the_embedding_tier_is_checked(monkeypatch, capsys):
    _stub(monkeypatch, ("OK", "all five installed"))
    monkeypatch.setattr(verify, "check_embedding", lambda cfg: ("FAIL", "hash noise"))
    assert verify.run(RunConfig()) == 1
    assert "Embedding" in capsys.readouterr().out
