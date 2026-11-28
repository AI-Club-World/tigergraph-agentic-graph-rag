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

# Round 2 (docs/round-2/DESIGN.md, gate G1): the fact layer, added to
# the existing graph by a schema change job, and its two queries. Installed
# separately, so a Round-1 build is unchanged.
ROUND2_SCHEMA_PATH = _GRAPH_DIR / "schema_round2.gsql"
ROUND2_QUERY_FILES = ("q5s_search.gsql", "q6_claims.gsql")
ROUND2_VERTEX_TYPES = frozenset({"Dataset", "Source", "Entity", "Claim"})

# Round 2 answer layer (docs/round-2/SOLUTION-DESIGN.md §2-3): Athlete/WON and
# SourceRecord/REPORTS_ON by a second schema change job, and the ten tool queries.
R2_ANSWER_SCHEMA_PATH = _GRAPH_DIR / "schema_r2_answer.gsql"
R2_ANSWER_VERTEX_TYPES = frozenset({"Athlete", "SourceRecord"})
R2_QUERY_FILES = (
    "r2_find_events.gsql", "r2_medals_by_nation.gsql", "r2_event_series.gsql", "r2_athlete_medals.gsql",
    "r2_repeat_winners.gsql", "r2_entity_facts.gsql", "r2_find_entities.gsql", "r2_source_records.gsql",
    "r2_text_search.gsql", "r2_read_document.gsql",
)

__all__ = [
    "R2_ANSWER_SCHEMA_PATH", "R2_ANSWER_VERTEX_TYPES", "R2_QUERY_FILES", "has_r2_answer_schema",
    "install_r2_answer",
    "SCHEMA_PATH", "QUERIES_DIR", "QUERY_FILES", "ROUND2_SCHEMA_PATH", "ROUND2_QUERY_FILES",
    "has_round2_schema", "install_schema", "install_queries", "install_round2",
]

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


def has_round2_schema(client: TigerGraphClient) -> bool:
    """Whether the Round-2 types exist on the graph (False offline)."""
    client._ensure_connection()
    conn = client.conn
    if conn is None or not hasattr(conn, "getVertexTypes"):
        return False
    types = conn.getVertexTypes()
    return isinstance(types, list) and ROUND2_VERTEX_TYPES <= set(types)


def _wait_for(check, attempts: int = 12, delay_s: float = 5.0) -> bool:
    """Schema-change jobs return before `getVertexTypes` shows the new types
    (seen on Savanna); poll `check()` for up to ~1 minute."""
    import time

    for i in range(attempts):
        if check():
            return True
        if i < attempts - 1:
            time.sleep(delay_s)
    return False


def install_round2(client: TigerGraphClient) -> list[str]:
    """Add the Round-2 types (once) and install Q5S and Q6. Never drops the
    graph; a graph that already has the types only gets the queries."""
    client._ensure_connection()
    if client.conn is None:
        raise RuntimeError("No TigerGraph connection available; cannot install the Round-2 schema")
    results = []
    if not has_round2_schema(client):
        results.append(client.conn.gsql(ROUND2_SCHEMA_PATH.read_text(encoding="utf-8")))
        if hasattr(client.conn, "getVertexTypes") and not _wait_for(lambda: has_round2_schema(client)):
            raise RuntimeError(f"Round-2 schema not installed: {str(results[-1])[-300:]}")
    for filename in ROUND2_QUERY_FILES:
        results.append(client.conn.gsql((QUERIES_DIR / filename).read_text(encoding="utf-8")))
    installed = client.conn.getInstalledQueries()
    names = {n.rsplit("/", 1)[-1] for n in installed}
    missing = [f for f in ROUND2_QUERY_FILES if f.removesuffix(".gsql") not in names]
    if missing:
        raise RuntimeError("Round-2 queries not installed: " + ", ".join(missing))
    return results



def has_r2_answer_schema(client: TigerGraphClient) -> bool:
    """Whether Athlete and SourceRecord exist on the graph (False offline)."""
    client._ensure_connection()
    conn = client.conn
    if conn is None or not hasattr(conn, "getVertexTypes"):
        return False
    types = conn.getVertexTypes()
    return isinstance(types, list) and R2_ANSWER_VERTEX_TYPES <= set(types)


def install_r2_answer(client: TigerGraphClient) -> list[str]:
    """Add the Round-2 answer types (once) and install the ten r2_* queries.
    Never drops anything; a graph that already has the types only gets the
    queries (CREATE OR REPLACE)."""
    client._ensure_connection()
    if client.conn is None:
        raise RuntimeError("No TigerGraph connection available; cannot install the Round-2 answer layer")
    results = []
    if not has_r2_answer_schema(client):
        results.append(client.conn.gsql(R2_ANSWER_SCHEMA_PATH.read_text(encoding="utf-8")))
        if hasattr(client.conn, "getVertexTypes") and not _wait_for(lambda: has_r2_answer_schema(client)):
            raise RuntimeError(f"Round-2 answer schema not installed: {str(results[-1])[-300:]}")
    for filename in R2_QUERY_FILES:
        results.append(client.conn.gsql((QUERIES_DIR / filename).read_text(encoding="utf-8")))
    installed = client.conn.getInstalledQueries()
    names = {n.rsplit("/", 1)[-1] for n in installed}
    missing = [f for f in R2_QUERY_FILES if f.removesuffix(".gsql") not in names]
    if missing:
        raise RuntimeError("Round-2 queries not installed: " + ", ".join(missing))
    return results
