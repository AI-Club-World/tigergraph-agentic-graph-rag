"""TigerGraph client interface wrapping pyTigerGraph and Q1-Q5 queries."""

from __future__ import annotations

import logging
from typing import Any

from ogr.common.config import RunConfig, get_default_config

logger = logging.getLogger(__name__)


class TigerGraphClient:
    """Client for TigerGraph RESTPP and installed queries.
    Provides direct access to Q5 hybrid_search per TECHNICAL-SPEC §3 and AD-7.
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
        self.last_query_args: dict[str, Any] = {}

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
    ) -> list[dict[str, Any]]:
        """Q5: hybrid_search(query_vector, k, vtype, candidate_set).
        Executes vectorSearch over the specified vertex type (Chunk or OlympicEvent).
        Returns top-k records with resolved parent doc_id via HAS_CHUNK for chunks.
        """
        # Record arguments for inspection and guard test assertion
        self.last_query_args = {
            "query_vector": query_vector,
            "k": k,
            "vtype": vtype,
            "candidate_set": candidate_set,
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
            return []

        try:
            params = {
                "query_vector": query_vector,
                "k": k,
                "vtype": vtype,
                "candidate_set": candidate_set or [],
            }
            # Execute installed query q5_hybrid_search
            raw_res = self.conn.runInstalledQuery("q5_hybrid_search", params)
            # Normalize returned records
            return self._normalize_q5_results(raw_res)
        except Exception as e:
            logger.error("Error executing Q5 hybrid_search: %s", e)
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
                    "score": float(item.get("score", attributes.get("score", 0.0))),
                })
        return chunks

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
            return []

        try:
            raw = self.conn.runInstalledQuery(query_name, params)
            if not raw:
                return []
            # Unwrap the first result block if it contains a list key
            if isinstance(raw, list) and raw and isinstance(raw[0], dict):
                for v in raw[0].values():
                    if isinstance(v, list):
                        return v
            return raw if isinstance(raw, list) else []
        except Exception as e:
            logger.error("Error running query '%s': %s", query_name, e)
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
            return []

        all_chunks: list[dict[str, Any]] = []
        for doc_id in doc_ids:
            try:
                # Navigate HAS_CHUNK edge from Document to Chunk vertices
                raw = self.conn.getEdgesByType("HAS_CHUNK", "Document", doc_id)
                for item in (raw or []):
                    all_chunks.append({
                        "chunk_id": item.get("to_id", ""),
                        "doc_id": doc_id,
                        "text": item.get("attributes", {}).get("text", ""),
                        "seq": item.get("attributes", {}).get("seq", 0),
                    })
            except Exception as e:
                logger.warning("HAS_CHUNK expansion failed for %s: %s", doc_id, e)
        return all_chunks

    def get_vocabulary(self, vtype: str) -> list[str]:
        """Retrieve distinct values for a vertex type (Games, Sport, Venue names).

        Used by EntityLinker to build its closed vocabularies at startup.
        """
        if self.mock_chunks is not None:
            return []

        self._ensure_connection()
        if self.conn is None:
            return []

        try:
            vertices = self.conn.getVertices(vtype)
            attr_map = {"Games": "games_id", "Sport": "sport_name", "Venue": "venue_name"}
            attr = attr_map.get(vtype, "name")
            return [
                v.get("attributes", {}).get(attr, v.get("v_id", ""))
                for v in (vertices or [])
                if v.get("attributes", {}).get(attr) or v.get("v_id")
            ]
        except Exception as e:
            logger.warning("Failed to load vocabulary for %s: %s", vtype, e)
            return []

