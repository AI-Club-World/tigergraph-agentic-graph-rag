"""Dataset adapters (ROUND2-DESIGN.md §1): one per dataset format."""

from __future__ import annotations

from ogr.datasets.base import DatasetAdapter

__all__ = ["adapter_for", "detect_adapter"]

# Record fields that mark a dataset of dated, attributed statements.
_STATEMENT_FIELDS = ("published_at", "published", "timestamp", "source", "source_id")


def adapter_for(name: str, dataset_id: str) -> DatasetAdapter:
    """The adapter registered under `name`."""
    from ogr.datasets.block_records import BlockRecordAdapter
    from ogr.datasets.olympic import OlympicAdapter

    adapters = {"olympic": OlympicAdapter, "block_records": BlockRecordAdapter}
    if name not in adapters:
        raise ValueError(f"unknown dataset adapter {name!r}; known: {', '.join(sorted(adapters))}")
    return adapters[name](dataset_id)


def detect_adapter(path, sample: int = 50) -> str:
    """`block_records` when the sidecar names it or most sampled records
    carry statement metadata (publication time, source); else `olympic`
    (the Round-1 corpus shape). [ASSUMPTION] until the Round-2 format is known."""
    from pathlib import Path

    from ogr.datasets.base import read_jsonl
    from ogr.ingest.dataset_meta import read_meta

    path = Path(path)
    named = read_meta(path).get("adapter")
    if named:
        return str(named)
    rows = []
    for row in read_jsonl(path):
        rows.append(row)
        if len(rows) >= sample:
            break
    marked = sum(1 for r in rows if any(r.get(k) for k in _STATEMENT_FIELDS))
    return "block_records" if rows and marked * 2 > len(rows) else "olympic"

