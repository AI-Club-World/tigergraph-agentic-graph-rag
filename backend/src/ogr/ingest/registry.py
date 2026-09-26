"""Which corpora are loaded into the graph — multi-dataset RAG.

Every dataset is loaded into the same graph, so a new dataset never disturbs
the ones already there. The registry records, per dataset, the vertex ids it
wrote, so rebuilding one dataset can remove exactly its data (ids another
dataset also wrote are kept) and reload it. The schema is installed — which
drops the graph — only for a first build or an explicit reset.

Stored as JSON next to the batch runs (`out/datasets.json`, runtime state, not
committed). Its `schema` block records the embedding model and dimension the
graph was built with; a graph built with a different dimension cannot take
new vectors and must be reset.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
ID_KINDS = (("Document", "doc_ids"), ("OlympicEvent", "event_ids"), ("Chunk", "chunk_ids"))


class DatasetRegistry:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema": None, "datasets": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, name: str) -> dict[str, Any] | None:
        return self.read()["datasets"].get(name)

    def reset(self, embedding_model: str, embedding_dim: int) -> None:
        """The graph was (re)created empty with this embedding schema."""
        with _LOCK:
            self._write({
                "schema": {"embedding_model": embedding_model, "embedding_dim": embedding_dim},
                "datasets": {},
            })

    def record(self, name: str, ids: dict[str, list[str]], counts: dict[str, int], file_bytes: int) -> None:
        with _LOCK:
            data = self.read()
            data["datasets"][name] = {
                "built_at": datetime.now(UTC).isoformat(),
                "file_bytes": file_bytes,
                **counts,
                **{key: sorted(set(ids.get(key, []))) for _, key in ID_KINDS},
            }
            self._write(data)

    def removable_ids(self, name: str) -> dict[str, list[str]]:
        """Ids `name` wrote that no other dataset also wrote, per vertex type."""
        data = self.read()
        mine = data["datasets"].get(name) or {}
        result: dict[str, list[str]] = {}
        for vtype, key in ID_KINDS:
            others = {i for n, d in data["datasets"].items() if n != name for i in d.get(key, [])}
            result[vtype] = [i for i in mine.get(key, []) if i not in others]
        return result

    def forget(self, name: str) -> None:
        with _LOCK:
            data = self.read()
            data["datasets"].pop(name, None)
            self._write(data)

    def summary(self) -> dict[str, Any]:
        """Registry without the id lists — what the UI shows."""
        data = self.read()
        return {
            "tracked": self.exists,
            "schema": data.get("schema"),
            "datasets": {
                name: {k: v for k, v in entry.items() if not k.endswith("_ids")}
                for name, entry in data["datasets"].items()
            },
        }
