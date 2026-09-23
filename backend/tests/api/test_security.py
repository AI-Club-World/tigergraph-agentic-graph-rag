"""StreamTokenStore: single-use, scoped, expiring — and bounded (AUDIT-03 follow-up)."""

from __future__ import annotations

from ogr.api import security
from ogr.api.security import StreamTokenStore


def test_token_is_single_use_and_scoped():
    store = StreamTokenStore()
    token = store.issue("q1")
    assert store.consume(token, "q2") is False  # wrong scope does not burn it
    assert store.consume(token, "q1") is True
    assert store.consume(token, "q1") is False


def test_used_and_expired_tokens_are_removed(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: now[0])
    store = StreamTokenStore(ttl_s=10)
    used = store.issue("a")
    store.consume(used, "a")
    store.issue("b")
    now[0] += 11  # "b" expires
    store.issue("c")
    assert [e.scope_id for e in store._entries.values()] == ["c"]


def test_expired_token_is_rejected(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(security.time, "monotonic", lambda: now[0])
    store = StreamTokenStore(ttl_s=10)
    token = store.issue("a")
    now[0] += 11
    assert store.consume(token, "a") is False
