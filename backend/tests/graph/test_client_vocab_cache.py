"""Vocabularies are fetched once per client, not once per query (AUDIT-03)."""

from __future__ import annotations

from unittest.mock import MagicMock

from ogr.common.config import RunConfig
from ogr.graph.client import TigerGraphClient


def test_vocabulary_is_fetched_once_per_client():
    conn = MagicMock()
    conn.getVertices.return_value = [{"v_id": "v1", "attributes": {"venue_name": "Olympic Stadium"}}]
    client = TigerGraphClient(config=RunConfig(), conn=conn)
    assert client.get_vocabulary("Venue") == ["Olympic Stadium"]
    assert client.get_vocabulary("Venue") == ["Olympic Stadium"]
    assert conn.getVertices.call_count == 1


def test_empty_vocabulary_is_not_cached():
    conn = MagicMock()
    conn.getVertices.side_effect = [[], [{"v_id": "v1", "attributes": {"venue_name": "Riocentro"}}]]
    client = TigerGraphClient(config=RunConfig(), conn=conn)
    assert client.get_vocabulary("Venue") == []
    assert client.get_vocabulary("Venue") == ["Riocentro"]
