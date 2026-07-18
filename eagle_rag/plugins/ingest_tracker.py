"""Per-ingest collection usage tracker (G28/G30)."""

from __future__ import annotations

from contextvars import ContextVar

__all__ = [
    "clear_ingest_collections",
    "record_ingest_collection",
    "snapshot_ingest_collections",
]

_collections: ContextVar[set[str] | None] = ContextVar("ingest_collections", default=None)


def clear_ingest_collections() -> None:
    _collections.set(set())


def record_ingest_collection(collection: str) -> None:
    if not collection:
        return
    current = _collections.get()
    if current is None:
        current = set()
        _collections.set(current)
    current.add(collection)


def snapshot_ingest_collections() -> list[str]:
    current = _collections.get()
    if not current:
        return []
    return sorted(current)
