"""Installs the GRAPH-01 schema and the GRAPH-07 query library.

Both installers just hand the committed `.gsql` text to pyTigerGraph's
`conn.gsql()`, which is the same mechanism `graph/client.py` already relies
on being available (it calls `conn.runInstalledQuery` for queries this module
installs). Nothing here can be verified beyond "the file exists and contains
the expected names" without a live TigerGraph connection — a real install is
the first true syntax check.
"""

from __future__ import annotations

from pathlib import Path

from ogr.common.embedding_models import EMBEDDING_MODELS
from ogr.graph.client import TigerGraphClient

_GRAPH_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = _GRAPH_DIR / "schema.gsql"
QUERIES_DIR = _GRAPH_DIR / "queries"

QUERY_FILES = (
    "q1_lookup.gsql",
    "q2_count_where.gsql",
    "q3_argmax.gsql",
    "q4_traverse.gsql",
    "q5_hybrid_search.gsql",
)

__all__ = ["SCHEMA_PATH", "QUERIES_DIR", "QUERY_FILES", "install_schema", "install_queries"]

EXPECTED_VERTEX_TYPES = frozenset(
    {"Document", "OlympicEvent", "Games", "Sport", "Venue", "Chunk"}
    | {m.vertex_type for m in EMBEDDING_MODELS.values()}
)


def install_schema(client: TigerGraphClient) -> str:
    """Run schema.gsql against the client's connection. Idempotent — the
    file drops the graph and its types before recreating them.
    """
    client._ensure_connection()
    if client.conn is None:
        raise RuntimeError("No TigerGraph connection available; cannot install schema")
    gsql_text = SCHEMA_PATH.read_text(encoding="utf-8")
    output = client.conn.gsql(gsql_text)
    # conn.gsql() reports most failures as text, not exceptions: confirm the
    # vertex types exist, so a failed install fails the build instead of the
    # registry recording an empty graph that every later load trips over.
    if hasattr(client.conn, "getVertexTypes"):
        types = client.conn.getVertexTypes()
        if isinstance(types, list):
            missing = sorted(EXPECTED_VERTEX_TYPES - set(types))
            if missing:
                raise RuntimeError(
                    f"Schema not installed — missing vertex types {', '.join(missing)}: {str(output)[-300:]}"
                )
    return output


def install_queries(client: TigerGraphClient) -> list[str]:
    """INTERPRET+install each of Q1-Q5, in order. Each install can take
    ~1 minute and blocks concurrent operations (TECHNICAL-SPEC §3) — install
    once, near the end of a build, not per run.
    """
    client._ensure_connection()
    if client.conn is None:
        raise RuntimeError("No TigerGraph connection available; cannot install queries")

    results = []
    for filename in QUERY_FILES:
        gsql_text = (QUERIES_DIR / filename).read_text(encoding="utf-8")
        results.append(client.conn.gsql(gsql_text))

    # conn.gsql() raises only for some statement types; a failed CREATE or
    # INSTALL QUERY comes back as text. Ask the server what is installed so a
    # broken query fails the build instead of silently returning [] later.
    installed = client.conn.getInstalledQueries()
    names = {n.rsplit("/", 1)[-1] for n in (installed if isinstance(installed, (list, set)) else installed)}
    failed = [
        f"{filename}: {str(output)[-300:]}"
        for filename, output in zip(QUERY_FILES, results, strict=True)
        if filename.removesuffix(".gsql") not in names
    ]
    if failed:
        raise RuntimeError("GSQL queries not installed — " + " | ".join(failed))
    return results
