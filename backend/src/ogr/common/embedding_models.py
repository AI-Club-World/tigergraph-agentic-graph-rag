"""The selectable embedding models (config-docs/EMBEDDING-SWITCHING.md).

Each model owns one TigerGraph vertex type (`vertex_type`) holding one
embedding per canonical `Chunk`, with its own HNSW index. A model is
identified by its `key` — never by its dimension: four of the five are
1024-dim, and equal shapes are not the same embedding space.

`query_prefix` / `doc_prefix` are the retrieval prompts each model was
trained with (from its model card); a query embedded without its prompt
lands measurably off the documents it should match.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "DEFAULT_MODEL_KEY",
    "EMBEDDING_MODELS",
    "MAX_STORED_MODELS",
    "EmbeddingModel",
    "UnknownEmbeddingModel",
    "resolve_model",
]

# At most this many models' embeddings coexist in the graph.
MAX_STORED_MODELS = 2


@dataclass(frozen=True)
class EmbeddingModel:
    key: str
    label: str
    dim: int
    vertex_type: str
    hf_id: str
    query_prefix: str = ""
    doc_prefix: str = ""
    # Workers AI model id, when Cloudflare hosts this exact model.
    cloudflare_id: str | None = None
    trust_remote_code: bool = False

    def public(self) -> dict[str, object]:
        return {"key": self.key, "label": self.label, "dim": self.dim, "vertex_type": self.vertex_type}


_RETRIEVAL_QUERY = "Represent this sentence for searching relevant passages: "

EMBEDDING_MODELS: dict[str, EmbeddingModel] = {
    m.key: m
    for m in (
        EmbeddingModel(
            key="qwen3-embedding-0.6b",
            label="Qwen3-Embedding-0.6B",
            dim=1024,
            vertex_type="Embedding_Qwen",
            hf_id="Qwen/Qwen3-Embedding-0.6B",
            query_prefix=(
                "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
            ),
        ),
        EmbeddingModel(
            key="embeddinggemma-300m",
            label="EmbeddingGemma-300M",
            dim=768,
            vertex_type="Embedding_EmbeddingGemma",
            hf_id="google/embeddinggemma-300m",
            query_prefix="task: search result | query: ",
            doc_prefix="title: none | text: ",
        ),
        EmbeddingModel(
            key="gte-large-en-v1.5",
            label="gte-large-en-v1.5",
            dim=1024,
            vertex_type="Embedding_GteLarge",
            hf_id="Alibaba-NLP/gte-large-en-v1.5",
            trust_remote_code=True,
        ),
        EmbeddingModel(
            key="mxbai-embed-large-v1",
            label="mxbai-embed-large-v1",
            dim=1024,
            vertex_type="Embedding_Mxbai",
            hf_id="mixedbread-ai/mxbai-embed-large-v1",
            query_prefix=_RETRIEVAL_QUERY,
        ),
        EmbeddingModel(
            key="bge-large-en-v1.5",
            label="bge-large-en-v1.5",
            dim=1024,
            vertex_type="Embedding_BGELarge",
            hf_id="BAAI/bge-large-en-v1.5",
            query_prefix=_RETRIEVAL_QUERY,
            cloudflare_id="@cf/baai/bge-large-en-v1.5",
        ),
    )
}

# Served by Cloudflare Workers AI when its credentials are set, locally otherwise.
DEFAULT_MODEL_KEY = "bge-large-en-v1.5"


class UnknownEmbeddingModel(ValueError):
    pass


def resolve_model(name: str | None) -> EmbeddingModel:
    """A model by key, label, Hugging Face id or Cloudflare id (case-insensitive)."""
    wanted = (name or DEFAULT_MODEL_KEY).strip().lower()
    for model in EMBEDDING_MODELS.values():
        aliases = {model.key, model.label.lower(), model.hf_id.lower(), (model.cloudflare_id or "").lower()}
        if wanted in aliases:
            return model
    raise UnknownEmbeddingModel(
        f"Unknown embedding model {name!r}; choose one of: {', '.join(EMBEDDING_MODELS)}"
    )
