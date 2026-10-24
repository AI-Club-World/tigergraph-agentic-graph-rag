"""Dataset adapters (ROUND2-DESIGN.md §1): one per dataset format."""

from __future__ import annotations

from ogr.datasets.base import DatasetAdapter

__all__ = ["adapter_for"]


def adapter_for(name: str, dataset_id: str) -> DatasetAdapter:
    """The adapter registered under `name`."""
    from ogr.datasets.block_records import BlockRecordAdapter
    from ogr.datasets.olympic import OlympicAdapter

    adapters = {"olympic": OlympicAdapter, "block_records": BlockRecordAdapter}
    if name not in adapters:
        raise ValueError(f"unknown dataset adapter {name!r}; known: {', '.join(sorted(adapters))}")
    return adapters[name](dataset_id)
