"""TigerGraph client interface wrapping pyTigerGraph and Q1-Q5 queries."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

from ogr.common.config import RunConfig, get_default_config
from ogr.common.contracts import GRAPH_ERROR_PREFIX
from ogr.common.embedding_models import EMBEDDING_MODELS, EmbeddingModel, resolve_model

logger = logging.getLogger(__name__)


def drain_graph_errors(client: Any) -> list[str]:
    """`client.drain_errors()`, tolerating stand-in clients that lack it."""
    drain = getattr(client, "drain_errors", None)
    errors = drain() if callable(drain) else []
    return errors if isinstance(errors, list) else []


# Failures worth one more try: Savanna intermittently rejects a request with an
# empty-token auth error (REST-10016) or a gateway 5xx, e.g. while a workspace
# is (re)starting. Anything else (a GSQL error, a bad parameter) is not retried.
_TRANSIENT = ("REST-10016", "500 Server Error", "502 Server Error", "503 Server Error", "504 Server Error")
READ_ATTEMPTS = 3
READ_BACKOFF_S = 2.0


class GraphUnavailableError(RuntimeError):
    """A graph read failed after its retries on a live connection."""


def _read_with_retry(call, *args, **kwargs):
    """`call(*args, **kwargs)`, retried with backoff on a transient failure."""
    for attempt in range(1, READ_ATTEMPTS + 1):
        try:
            return call(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - classified below, re-raised when not transient
            if attempt == READ_ATTEMPTS or not any(t in str(e) for t in _TRANSIENT):
                raise
            logger.warning(
                "Transient graph failure (%s); retry %d/%d", str(e)[:80], attempt, READ_ATTEMPTS - 1
            )
            time.sleep(READ_BACKOFF_S * 2 ** (attempt - 1))
    raise AssertionError("unreachable")


def graph_error_detail(errors: list[str]) -> str | None:
    return GRAPH_ERROR_PREFIX + "; ".join(errors) if errors else None


class TigerGraphClient:
    """Client for TigerGraph RESTPP and installed queries.
    Provides direct access to Q5 hybrid_search per TECHNICAL-SPEC §3 and AD-7.

    Thread safety: one instance is shared by P1/P2/P3 running in worker
    threads. pyTigerGraph >= 2.0 gives each calling thread its own
    `requests.Session`, so concurrent calls on the shared connection do not
    share sockets; the lazy connection setup is serialised by `_conn_lock`.
    """

    def __init__(
        self,
        config: RunConfig | None = None,
        conn: Any | None = None,
        mock_chunks: list[dict[str, Any]] | None = None,
    ) -> None:
        self.config = config or get_default_config()
        self.conn = conn
        self.mock_chunks = mock_chunks
        # Test-only: the P1 guard test asserts on the last Q5 arguments. No
        # production code reads it — under concurrent callers it is simply
        # whichever call wrote last.
        self.last_query_args: dict[str, Any] = {}
        self._conn_lock = threading.Lock()
        # Games/Sport/Venue are static for the life of a loaded graph, so each
        # is fetched once per client rather than once per query.
        self._vocab_cache: dict[str, list[str]] = {}
        # Query failures since the caller last drained them. Retrieval still
        # returns [] on failure (the pipelines answer from what they have),
        # but the failure is reported on the trace step / record instead of
        # reading as "no evidence". Per thread: concurrent questions share
        # one client, and each drains in the thread that ran its query.
        self._errors = threading.local()

    def _note_error(self, message: str) -> None:
        if not hasattr(self._errors, "items"):
            self._errors.items = []
        self._errors.items.append(message)

    def drain_errors(self) -> list[str]:
        """Query errors recorded in this thread since the last drain."""
        items = getattr(self._errors, "items", [])
        self._errors.items = []
        return items

    def _ensure_connection(self) -> None:
        """Initializes pyTigerGraph connection if not already created.

        Four credential styles are supported, in the order pyTigerGraph
        prefers them. Which one a Savanna workspace wants depends on how it
        was provisioned, so all are passed through from configuration rather
        than hard-coded:

          TG_JWT_TOKEN   JWT bearer token (TigerGraph 4.x / Savanna)
          TG_TOKEN       pre-minted REST++ token
          TG_SECRET      a workspace secret, from which a token is minted
          TG_USERNAME/TG_PASSWORD   basic credentials

        Only non-empty values are forwarded: pyTigerGraph treats an empty
        string as "not supplied" but an explicit None can raise, so the
        kwargs are assembled rather than always passed.
        """
        if self.conn is not None:
            return
        with self._conn_lock:
            if self.conn is None:
                self._connect()

    def _connect(self) -> None:
        try:
            import pyTigerGraph as tg

            kwargs: dict[str, Any] = {
                "host": self.config.tg_host,
                "graphname": self.config.tg_graphname,
            }
            # Savanna: let pyTigerGraph derive the TLS endpoints.
            if self.config.tg_cloud:
                kwargs["tgCloud"] = True
            if self.config.tg_restpp_port is not None:
                kwargs["restppPort"] = self.config.tg_restpp_port
            if self.config.tg_gs_port is not None:
                kwargs["gsPort"] = self.config.tg_gs_port

            if self.config.tg_jwt_token:
                kwargs["jwtToken"] = self.config.tg_jwt_token
            elif self.config.tg_token:
                kwargs["apiToken"] = self.config.tg_token
            elif self.config.tg_secret:
                kwargs["gsqlSecret"] = self.config.tg_secret
            else:
                kwargs["username"] = self.config.tg_username
                kwargs["password"] = self.config.tg_password

            if self.config.tg_use_cert:
                kwargs["useCert"] = True
            if self.config.tg_cert_path:
                kwargs["certPath"] = self.config.tg_cert_path

            self.conn = tg.TigerGraphConnection(**kwargs)
            logger.info(
                "TigerGraph connection initialised: host=%s graph=%s cloud=%s auth=%s",
                self.config.tg_host,
                self.config.tg_graphname,
                self.config.tg_cloud,
                next(
                    (k for k in ("jwtToken", "apiToken", "gsqlSecret", "username") if k in kwargs),
                    "none",
                ),
            )
        except Exception as e:
            logger.warning("Failed to initialize live TigerGraph connection: %s", e)
            self.conn = None

    def hybrid_search(
        self,
        query_vector: list[float],
        k: int = 10,
        vtype: str = "Chunk",
        candidate_set: list[str] | None = None,
        embedding_model: str | None = None,
    ) -> list[dict[str, Any]]:
        """Q5: vector search over the chunks, in `embedding_model`'s own index.

        `query_vector` must come from that same model: callers embed the query
        and pass the model key from one config value, and the index searched
        (`emb_type`) is derived from that key here — never from the vector's
        length, which four of the five models share.
        """
        model = resolve_model(embedding_model or self.config.embedding_model)
        # Record arguments for inspection and guard test assertion
        self.last_query_args = {
            "query_vector": query_vector,
            "k": k,
            "vtype": vtype,
            "candidate_set": candidate_set,
            "embedding_model": model.key,
            "emb_type": model.vertex_type,
        }

        # If mock chunks are provided (for testing or offline evaluation)
        if self.mock_chunks is not None:
            results = []
            for chunk in self.mock_chunks:
                # Respect vtype if present in mock data
                if chunk.get("vtype", "Chunk") != vtype:
                    continue
                # If candidate_set is specified, filter by candidate_set
                if candidate_set is not None and chunk.get("chunk_id") not in candidate_set:
                    continue
                results.append(chunk)
            return results[:k]

        # Live query execution
        self._ensure_connection()
        if self.conn is None:
            logger.warning("TigerGraph connection not available; returning empty result set")
            self._note_error("q5_hybrid_search: TigerGraph unavailable")
            return []

        if len(query_vector) != model.dim:
            # A vector of another shape cannot be from this model: refuse it
            # loudly rather than let the query return [] as "no matches".
            raise ValueError(
                f"Query vector has {len(query_vector)} dims; {model.label} embeddings have {model.dim}"
            )
        try:
            params = {
                "query_vector": query_vector,
                "k": k,
                "emb_type": model.vertex_type,
                "candidate_set": candidate_set or [],
            }
            # Execute installed query q5_hybrid_search
            raw_res = _read_with_retry(self.conn.runInstalledQuery, "q5_hybrid_search", params)
            # Normalize returned records
            return self._normalize_q5_results(raw_res)
        except Exception as e:
            logger.error("Error executing Q5 hybrid_search: %s", e)
            self._note_error(f"q5_hybrid_search: {e}")
            return []

    def _normalize_q5_results(self, raw_res: Any) -> list[dict[str, Any]]:
        """Normalizes raw TigerGraph query output into standard chunk dicts."""
        chunks: list[dict[str, Any]] = []
        if not raw_res:
            return chunks

        # TigerGraph queries return a list of result maps
        items = raw_res
        if isinstance(raw_res, list) and len(raw_res) > 0 and isinstance(raw_res[0], dict):
            # Check for standard TigerGraph query output keys like 'results' or 'top_chunks'
            if "results" in raw_res[0]:
                items = raw_res[0]["results"]
            elif "top_chunks" in raw_res[0]:
                items = raw_res[0]["top_chunks"]

        # vectorSearch returns the ranked vertices and their distances in two
        # separate PRINT blocks, so the scores have to be joined back on here.
        # The metric is COSINE, whose distance is 1 - similarity.
        distances: dict[str, float] = {}
        if isinstance(raw_res, list):
            for block in raw_res:
                if isinstance(block, dict) and isinstance(block.get("distances"), dict):
                    distances = block["distances"]
                    break

        if isinstance(items, list):
            for item in items:
                attributes = item.get("attributes", {}) if "attributes" in item else item
                v_id = item.get("v_id", attributes.get("id", ""))
                doc_id = attributes.get("doc_id", "")
                if not doc_id and "_" in v_id:
                    # Fallback parent doc_id extraction from QID_cX convention
                    doc_id = v_id.split("_")[0]

                chunks.append({
                    "chunk_id": v_id,
                    "doc_id": doc_id,
                    "text": attributes.get("text", attributes.get("content", "")),
                    "score": (
                        1.0 - float(distances[v_id])
                        if v_id in distances
                        else float(item.get("score", attributes.get("score", 0.0)))
                    ),
                })

        # The vertex set comes back in no particular order, so ranking has to
        # be applied here for the caller's top-k to mean anything.
        if distances:
            chunks.sort(key=lambda c: c["score"], reverse=True)
        return chunks

    # ── Per-model embedding storage (config-docs/EMBEDDING-SWITCHING.md) ──

    def _require_conn(self) -> Any:
        self._ensure_connection()
        if self.conn is None:
            raise ConnectionError("TigerGraph unreachable — set TG_HOST and credentials")
        return self.conn

    # pyTigerGraph's getVerticesById/delVerticesById send one REST request
    # per id (~0.4 s each on Savanna: hours for a 16k-chunk corpus). One
    # interpreted query per batch does the same in a single call; if the
    # server refuses it, the per-id calls remain the fallback.
    BULK_BATCH = 200

    def _interpreted(self, body: str, ids: list[str]) -> Any:
        graph = self.config.tg_graphname
        text = f"INTERPRET QUERY (SET<STRING> ids) FOR GRAPH {graph} {{\n{body}\n}}"
        return self._require_conn().runInterpretedQuery(text, {"ids": ids})

    def get_chunk_texts(self, chunk_ids: list[str]) -> dict[str, str]:
        """Canonical chunk text by id — what a re-embed job embeds. Ids not in
        the graph are simply absent from the result."""
        conn = self._require_conn()
        texts: dict[str, str] = {}
        for start in range(0, len(chunk_ids), self.BULK_BATCH):
            batch = chunk_ids[start:start + self.BULK_BATCH]
            try:
                raw = self._interpreted('Start = to_vertex_set(ids, "Chunk");\nPRINT Start;', batch)
                vertices = raw[0]["Start"] if raw else []
            except Exception as e:  # noqa: BLE001 - fall back to per-id reads
                logger.debug("Bulk chunk read unavailable (%s); reading per id", e)
                vertices = []
                for cid in batch:
                    try:
                        vertices += conn.getVerticesById("Chunk", [cid]) or []
                    except Exception:  # noqa: BLE001 - a missing id is reported by the caller
                        continue
            for v in vertices:
                texts[v.get("v_id", "")] = v.get("attributes", {}).get("text", "")
        return texts

    def delete_by_ids(self, vertex_type: str, ids: list[str]) -> int:
        """Delete vertices of one type by id (and so the edges touching them)."""
        conn = self._require_conn()
        if not _IDENTIFIER.match(vertex_type):
            raise ValueError(f"{vertex_type!r} is not a vertex type name")
        removed = 0
        for start in range(0, len(ids), self.BULK_BATCH):
            batch = ids[start:start + self.BULK_BATCH]
            try:
                raw = self._interpreted(
                    f'Start = to_vertex_set(ids, "{vertex_type}");\n'
                    "DELETE v FROM Start:v;\nPRINT Start.size() AS removed;",
                    batch,
                )
                removed += int((raw or [{}])[0].get("removed", 0))
            except Exception as e:  # noqa: BLE001 - fall back to per-id deletes
                logger.debug("Bulk delete unavailable (%s); deleting per id", e)
                removed += int(conn.delVerticesById(vertex_type, batch) or 0)
        return removed

    def upsert_embeddings(self, model: EmbeddingModel, rows: list[tuple[str, list[float]]]) -> int:
        """Write one model's embeddings for a batch of chunks, with their
        HAS_EMBEDDING edges. Idempotent: the embedding vertex's primary id is
        the chunk_id, so writing a chunk again (a resumed batch) overwrites
        that vertex and edge instead of adding a second one."""
        if not rows:
            return 0
        for chunk_id, vector in rows:
            if len(vector) != model.dim:
                raise ValueError(f"{chunk_id}: {len(vector)}-dim vector for {model.label} ({model.dim})")
        conn = self._require_conn()
        conn.upsertVertices(model.vertex_type, [(cid, {"emb": vector}) for cid, vector in rows])
        conn.upsertEdges("Chunk", "HAS_EMBEDDING", model.vertex_type, [(cid, cid, {}) for cid, _ in rows])
        return len(rows)

    def delete_embeddings(
        self, model: EmbeddingModel, chunk_ids: list[str] | None = None
    ) -> int:
        """Delete one model's embedding vertices — all of them, or those of
        `chunk_ids`. Deleting a vertex removes only the edges touching it, so
        this removes that model's vectors (and so its HNSW entries) and its
        HAS_EMBEDDING edges, and never a Chunk or another model's data: the
        only vertex type ever passed to TigerGraph is the model's own."""
        vertex_type = _embedding_type(model)
        conn = self._require_conn()
        if chunk_ids is None:
            return int(conn.delVertices(vertex_type) or 0)
        return self.delete_by_ids(vertex_type, chunk_ids)

    def count_embeddings(self, model: EmbeddingModel) -> int:
        return int(self._require_conn().getVertexCount(_embedding_type(model)) or 0)

    def _run_query(self, query_name: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Generic runner for installed Q1–Q4 queries.

        Returns raw list of result dicts, or empty list on failure/offline.
        Used by P3 tool agents (graph_traversal, aggregation, multi_hop).
        """
        # Mock mode: if mock_chunks provided return mock data for known queries
        if self.mock_chunks is not None:
            return []

        self._ensure_connection()
        if self.conn is None:
            logger.warning("TigerGraph unavailable; _run_query('%s') returning empty", query_name)
            self._note_error(f"{query_name}: TigerGraph unavailable")
            return []

        try:
            raw = _read_with_retry(self.conn.runInstalledQuery, query_name, params)
            if not raw:
                return []
            # Unwrap the first result block if it contains a list key
            if isinstance(raw, list) and raw and isinstance(raw[0], dict):
                for v in raw[0].values():
                    if isinstance(v, list):
                        return [_flatten_vertex(item) for item in v]
            return raw if isinstance(raw, list) else []
        except Exception as e:
            logger.error("Error running query '%s': %s", query_name, e)
            self._note_error(f"{query_name}: {e}")
            return []

    def _expand_has_chunk(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        """Expand Document vertices to their Chunks via the HAS_CHUNK edge.

        Used by the document_retrieval agent (prose fallback).
        """
        if self.mock_chunks is not None:
            # Return mock chunks whose doc_id matches any of the requested ids
            return [c for c in self.mock_chunks if c.get("doc_id") in doc_ids]

        self._ensure_connection()
        if self.conn is None:
            logger.warning("TigerGraph unavailable; _expand_has_chunk returning empty")
            self._note_error("HAS_CHUNK expansion: TigerGraph unavailable")
            return []

        all_chunks: list[dict[str, Any]] = []
        for doc_id in doc_ids:
            try:
                # This document's HAS_CHUNK edges, then the Chunk vertices they
                # point to (the edge carries no attributes; the text is on the
                # vertex). getEdgesByType would return every HAS_CHUNK edge in
                # the graph, whatever its source.
                edges = self.conn.getEdges("Document", doc_id, "HAS_CHUNK") or []
                chunk_ids = [e["to_id"] for e in edges if e.get("to_id")]
                if not chunk_ids:
                    continue
                for vertex in self.conn.getVerticesById("Chunk", chunk_ids) or []:
                    attributes = vertex.get("attributes", {})
                    all_chunks.append({
                        "chunk_id": vertex.get("v_id", ""),
                        "doc_id": doc_id,
                        "text": attributes.get("text", ""),
                        "seq": attributes.get("seq", 0),
                    })
            except Exception as e:
                logger.warning("HAS_CHUNK expansion failed for %s: %s", doc_id, e)
                self._note_error(f"HAS_CHUNK expansion for {doc_id}: {e}")
        return sorted(all_chunks, key=lambda c: (c["doc_id"], c["seq"]))

    def get_vocabulary(self, vtype: str) -> list[str]:
        """Retrieve distinct values for a vertex type (Games, Sport, Venue names).

        Used by EntityLinker to build its closed vocabularies at startup.
        """
        if self.mock_chunks is not None:
            return []
        if vtype in self._vocab_cache:
            return self._vocab_cache[vtype]

        self._ensure_connection()
        if self.conn is None:
            return []

        try:
            vertices = _read_with_retry(self.conn.getVertices, vtype)
            attr_map = {"Games": "games_id", "Sport": "sport_name", "Venue": "venue_name"}
            attr = attr_map.get(vtype, "name")
            vocab = [
                v.get("attributes", {}).get(attr, v.get("v_id", ""))
                for v in (vertices or [])
                if v.get("attributes", {}).get(attr) or v.get("v_id")
            ]
        except Exception as e:
            # Not an empty vocabulary: without it the linker resolves nothing
            # and every answer silently degrades. Raise, so the pipeline run
            # is an error (and a batch question is retried on resume).
            logger.error("Failed to load vocabulary for %s: %s", vtype, e)
            raise GraphUnavailableError(f"Failed to load vocabulary for {vtype}: {e}") from e
        # An empty result is not cached, so a graph loaded later is picked up.
        if vocab:
            self._vocab_cache[vtype] = vocab
        return vocab



_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _embedding_type(model: EmbeddingModel) -> str:
    """The model's own vertex type, checked against the catalog: a deletion
    can never be pointed at Chunk or any type outside the embedding types."""
    if EMBEDDING_MODELS.get(model.key) != model or not model.vertex_type.startswith("Embedding_"):
        raise ValueError(f"{model.vertex_type!r} is not an embedding vertex type")
    return model.vertex_type


def _flatten_vertex(item: Any) -> Any:
    """A printed vertex set ({v_id, v_type, attributes}) as a flat row, like
    the tuple rows every other branch prints. Q1's Document-title fallback
    prints vertices; nested, the evidence renderer showed only `v_type` and no
    doc_id, so the row carried no content and no citation."""
    if not (isinstance(item, dict) and isinstance(item.get("attributes"), dict)):
        return item
    row = {"v_id": item.get("v_id", ""), **item["attributes"]}
    if item.get("v_type") == "Document":
        row.setdefault("doc_id", item.get("v_id", ""))
    return row
