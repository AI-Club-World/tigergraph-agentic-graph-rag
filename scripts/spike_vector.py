"""Group 0 vector spike (implementation-plan-GRAPH.md, Gate G0).

Provisions a 2-vertex toy schema on TigerGraph Savanna with a 384-dim COSINE
`emb` attribute, loads 20 toy documents, embeds them locally with
all-MiniLM-L6-v2, polls /restpp/vector/status until Ready_for_query, and runs
one vectorSearch(). Writes observed timings to docs/spike-notes.md.

Env vars (see TECHNICAL-SPEC.md §14.2): TG_HOST, TG_USERNAME, TG_PASSWORD,
TG_SECRET, TG_GRAPHNAME. Loaded from a local, git-ignored .env if present.

STATUS: unverified against a live Savanna instance — the exact TigerVector
DDL/query syntax below (marked UNVERIFIED) is this spike's whole purpose to
confirm or correct; do not treat a clean run of this file as G0 passing until
someone with TigerGraph access has actually run it and updated
docs/spike-notes.md with real numbers.

Rollback per plan: if vectorSearch() is unavailable on the provisioned
version, stop and escalate — do not guess a workaround.
"""

import os
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

TG_HOST = os.environ["TG_HOST"]
TG_USERNAME = os.environ.get("TG_USERNAME", "tigergraph")
TG_PASSWORD = os.environ["TG_PASSWORD"]
TG_SECRET = os.environ.get("TG_SECRET", "")
TG_GRAPHNAME = os.environ.get("TG_GRAPHNAME", "SpikeVectorTest")

EMBED_MODEL_NAME = "all-MiniLM-L6-v2"
EMBED_DIM = 384
VERTEX_TYPE = "SpikeDoc"
POLL_TIMEOUT_S = 300
POLL_INTERVAL_S = 5

TOY_DOCS = [f"Toy Olympic document number {i} about a fictional event." for i in range(20)]

# UNVERIFIED: exact TigerVector DDL syntax. Written per publicly documented
# TigerGraph vector-index pattern; confirm against the provisioned Savanna
# version's GSQL shell before trusting this.
SCHEMA_DDL = f"""
USE GRAPH {TG_GRAPHNAME}
CREATE VERTEX {VERTEX_TYPE} (
  PRIMARY_ID id STRING,
  text STRING,
  emb VECTOR(dimension={EMBED_DIM}, metric="cosine")
) WITH primary_id_as_attribute="true"
"""

# UNVERIFIED: exact vectorSearch() call signature.
SEARCH_QUERY = f"""
USE GRAPH {TG_GRAPHNAME}
INTERPRET QUERY (VECTOR<{EMBED_DIM}> query_vec, INT k) FOR GRAPH {TG_GRAPHNAME} {{
  result = SELECT s FROM {VERTEX_TYPE}:s
           WHERE s.emb == vectorSearch({{{VERTEX_TYPE}.emb}}, query_vec, k);
  PRINT result;
}}
"""


def connect():
    import pyTigerGraph as tg

    conn = tg.TigerGraphConnection(
        host=TG_HOST, username=TG_USERNAME, password=TG_PASSWORD
    )
    if TG_SECRET:
        conn.getToken(TG_SECRET)

    try:
        conn.gsql(f"CREATE GRAPH {TG_GRAPHNAME} ()")
    except Exception as e:  # noqa: BLE001 - idempotent create, log and continue
        print(f"[spike] CREATE GRAPH ignored (likely already exists): {e}")

    conn.graphname = TG_GRAPHNAME
    if TG_SECRET:
        conn.getToken(TG_SECRET)
    return conn


def install_schema(conn):
    t0 = time.monotonic()
    conn.gsql(SCHEMA_DDL)
    return time.monotonic() - t0


def load_toy_docs(conn, model):
    embeddings = model.encode(TOY_DOCS, normalize_embeddings=True)
    vertices = [
        (f"doc-{i}", {"text": text, "emb": vec.tolist()})
        for i, (text, vec) in enumerate(zip(TOY_DOCS, embeddings))
    ]
    conn.upsertVertices(VERTEX_TYPE, vertices)
    return model


def poll_vector_status(conn):
    """UNVERIFIED: endpoint path/response shape per TECHNICAL-SPEC §11."""
    t0 = time.monotonic()
    deadline = t0 + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        resp = conn._req("GET", f"{conn.restppUrl}/restpp/vector/status")
        if isinstance(resp, dict) and resp.get("status") == "Ready_for_query":
            return time.monotonic() - t0
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(
        f"/restpp/vector/status did not report Ready_for_query within {POLL_TIMEOUT_S}s"
    )


def run_vector_search(conn, model):
    query_vec = model.encode(["a fictional Olympic event"], normalize_embeddings=True)[0].tolist()
    return conn.runInterpretedQuery(SEARCH_QUERY, params={"query_vec": query_vec, "k": 5})


def write_notes(results: dict):
    path = os.path.join(os.path.dirname(__file__), "..", "docs", "spike-notes.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"\n## Run {datetime.now(timezone.utc).isoformat()}\n\n")
        for k, v in results.items():
            f.write(f"- **{k}**: {v}\n")


def main():
    results = {}
    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMBED_MODEL_NAME)

        conn = connect()

        results["schema_install_s"] = install_schema(conn)
        load_toy_docs(conn, model)
        results["vector_index_lag_s"] = poll_vector_status(conn)

        search_result = run_vector_search(conn, model)
        results["vector_search_returned"] = len(search_result[0]["result"]) if search_result else 0
        results["status"] = "PASS"
    except Exception as e:  # noqa: BLE001 - top-level spike, report and escalate
        results["status"] = "FAIL"
        results["error"] = repr(e)
        write_notes(results)
        print(f"[spike] FAILED: {e}", file=sys.stderr)
        print(
            "[spike] Per plan rollback: if vectorSearch() is unavailable on this "
            "TigerGraph version, stop and escalate — do not guess a workaround.",
            file=sys.stderr,
        )
        sys.exit(1)

    write_notes(results)
    print(f"[spike] PASS: {results}")


if __name__ == "__main__":
    main()
