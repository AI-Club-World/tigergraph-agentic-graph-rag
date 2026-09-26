"""Every query, build and benchmark attempt, as an append-only JSONL log.

One line per attempt — successful, failed, refused or waiting on the user —
so the History view can show what was tried, with which dataset, provider and
model, how long it took and why it failed. Callers pass only non-secret
fields (provider and model names, never keys).
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()


class TrialLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def append(self, kind: str, status: str, **fields: Any) -> dict[str, Any]:
        entry = {
            "id": uuid.uuid4().hex,
            "at": datetime.now(UTC).isoformat(),
            "kind": kind,
            "status": status,
            **fields,
        }
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, default=str) + "\n")
        return entry

    def read(self, kind: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
        """Newest first; unreadable lines are skipped rather than failing the view."""
        if not self.path.exists():
            return []
        entries = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if kind is None or entry.get("kind") == kind:
                entries.append(entry)
        return entries[::-1][:limit]
