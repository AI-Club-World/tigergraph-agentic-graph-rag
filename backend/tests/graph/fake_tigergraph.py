"""An in-memory stand-in for the pyTigerGraph calls the embedding code makes,
with TigerGraph's own semantics where they matter for safety:

- upsert by primary id: writing an existing id overwrites it, never adds one;
- an edge is keyed by (type, from, to): upserting it again is a no-op;
- deleting a vertex deletes the edges touching it, and nothing else.
"""

from __future__ import annotations

from typing import Any


class FakeTigerGraph:
    def __init__(self) -> None:
        self.vertices: dict[str, dict[str, dict[str, Any]]] = {}
        self.edges: set[tuple[str, str, str, str, str]] = set()  # (src_type, src, etype, tgt_type, tgt)
        self.calls: list[tuple] = []

    # ── writes ──
    def upsertVertices(self, vtype: str, rows: list[tuple[str, dict]]) -> int:
        self.calls.append(("upsertVertices", vtype, [r[0] for r in rows]))
        for vid, attrs in rows:
            self.vertices.setdefault(vtype, {}).setdefault(vid, {}).update(attrs)
        return len(rows)

    def upsertEdges(self, src_type: str, etype: str, tgt_type: str, rows: list[tuple[str, str, dict]]) -> int:
        self.calls.append(("upsertEdges", src_type, etype, tgt_type))
        for src, tgt, _attrs in rows:
            self.edges.add((src_type, src, etype, tgt_type, tgt))
        return len(rows)

    def _delete(self, vtype: str, ids: set[str]) -> int:
        existing = self.vertices.get(vtype, {})
        gone = ids & set(existing)
        for vid in gone:
            del existing[vid]
        self.edges = {
            e for e in self.edges
            if not ((e[0] == vtype and e[1] in gone) or (e[3] == vtype and e[4] in gone))
        }
        return len(gone)

    def delVertices(self, vtype: str, where: str = "") -> int:
        self.calls.append(("delVertices", vtype))
        return self._delete(vtype, set(self.vertices.get(vtype, {})))

    def delVerticesById(self, vtype: str, ids: list[str]) -> int:
        self.calls.append(("delVerticesById", vtype, list(ids)))
        return self._delete(vtype, set(ids))

    # ── reads ──
    def getVerticesById(self, vtype: str, ids: list[str]) -> list[dict]:
        found = self.vertices.get(vtype, {})
        return [{"v_id": i, "attributes": found[i]} for i in ids if i in found]

    def getVertexCount(self, vtype: str) -> int:
        return len(self.vertices.get(vtype, {}))

    def edges_of(self, etype: str, tgt_type: str | None = None) -> set[tuple]:
        return {e for e in self.edges if e[2] == etype and (tgt_type is None or e[3] == tgt_type)}


def seeded(chunk_ids: list[str], models: dict[str, list[str]] | None = None) -> FakeTigerGraph:
    """Chunks (with a Document and HAS_CHUNK) plus, per vertex type, embeddings."""
    graph = FakeTigerGraph()
    graph.upsertVertices("Document", [("D1", {})])
    graph.upsertVertices("Chunk", [(cid, {"text": f"text of {cid}", "doc_id": "D1"}) for cid in chunk_ids])
    graph.upsertEdges("Document", "HAS_CHUNK", "Chunk", [("D1", cid, {}) for cid in chunk_ids])
    for vertex_type, ids in (models or {}).items():
        graph.upsertVertices(vertex_type, [(cid, {"emb": [0.1]}) for cid in ids])
        graph.upsertEdges("Chunk", "HAS_EMBEDDING", vertex_type, [(cid, cid, {}) for cid in ids])
    graph.calls.clear()
    return graph
