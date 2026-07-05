"""Document-level SHA-256 deduplication.

Implements an idempotent "check + register" flow backed by the PostgreSQL
``document_dedup`` table to prevent the same file from being parsed/indexed
twice. The composite primary key ``(sha256, kb_name)`` scopes deduplication
per knowledge base, so identical content may coexist under different
``kb_name`` tenants. All APIs are synchronous (psycopg2), for use by Celery
tasks.

Table schema is managed by Alembic + SQLModel; see ``eagle_rag.db.models.dedup``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.db import get_sync_conn

__all__ = [
    "compute_sha256",
    "compute_sha256_bytes",
    "check_duplicate",
    "register",
    "check_and_register",
]


# ---------------------------------------------------------------------------
# SHA-256 computation
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 1 << 20  # 1 MiB


def compute_sha256(file_path: str | Path) -> str:
    """Stream-compute the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with Path(file_path).open("rb") as fp:
        while True:
            chunk = fp.read(_CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def compute_sha256_bytes(data: bytes) -> str:
    """Compute the SHA-256 hex digest of a byte string."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Query and register
# ---------------------------------------------------------------------------


def _resolve_kb(kb_name: str | None) -> str:
    """Fall back to global ``settings.kb_name`` when ``kb_name`` is None."""
    return kb_name if kb_name is not None else get_settings().kb_name


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "sha256": row[0],
        "kb_name": row[1],
        "document_id": row[2],
        "object_key": row[3],
        "source_name": row[4],
        "created_at": row[5],
    }


_SELECT_SQL = (
    "SELECT sha256, kb_name, document_id, object_key, source_name, created_at "
    "FROM document_dedup WHERE sha256 = %s AND kb_name = %s"
)


def check_duplicate(sha256: str, kb_name: str | None = None) -> dict[str, Any] | None:
    """Look up the dedup table by sha256 + kb_name; return the record dict on hit, else ``None``."""
    kb = _resolve_kb(kb_name)
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_SQL, (sha256, kb))
            row = cur.fetchone()
    return _row_to_dict(row) if row is not None else None


def register(
    sha256: str,
    document_id: str,
    *,
    kb_name: str | None = None,
    object_key: str | None = None,
    source_name: str | None = None,
) -> None:
    """Register a dedup record; ``ON CONFLICT (sha256, kb_name) DO NOTHING``."""
    kb = _resolve_kb(kb_name)
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_dedup (sha256, kb_name, document_id, "
                "object_key, source_name) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (sha256, kb_name) DO NOTHING",
                (sha256, kb, document_id, object_key, source_name),
            )


def check_and_register(
    file_path: str | Path,
    document_id: str,
    *,
    kb_name: str | None = None,
    object_key: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Combine "check + register" into a single connection/transaction.

    Returns ``{"hit": bool, "sha256":..., "kb_name":..., "document_id":...,
    "object_key":..., "source_name":..., "created_at":...}``:

    - ``hit=True``: the (sha256, kb_name) already existed in the dedup table
      (including races where a concurrent insert won, then re-query hits);
      returns immediately.
    - ``hit=False``: this call registered the record for the first time;
      ``created_at`` is ``None``.
    """
    sha = compute_sha256(file_path)
    kb = _resolve_kb(kb_name)
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_SQL, (sha, kb))
            row = cur.fetchone()
            if row is not None:
                result = _row_to_dict(row)
                result["hit"] = True
                return result
            cur.execute(
                "INSERT INTO document_dedup (sha256, kb_name, document_id, "
                "object_key, source_name) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (sha256, kb_name) DO NOTHING",
                (sha, kb, document_id, object_key, source_name),
            )
            if cur.rowcount == 0:
                # Race: another writer inserted first; re-query to confirm.
                cur.execute(_SELECT_SQL, (sha, kb))
                row = cur.fetchone()
                result = (
                    _row_to_dict(row)
                    if row is not None
                    else {
                        "sha256": sha,
                        "kb_name": kb,
                        "document_id": document_id,
                        "object_key": object_key,
                        "source_name": source_name,
                        "created_at": None,
                    }
                )
                result["hit"] = True
                return result
    return {
        "hit": False,
        "sha256": sha,
        "kb_name": kb,
        "document_id": document_id,
        "object_key": object_key,
        "source_name": source_name,
        "created_at": None,
    }
