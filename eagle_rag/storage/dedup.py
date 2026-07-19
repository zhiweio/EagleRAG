"""Document-level SHA-256 deduplication.

Composite primary key ``(sha256, kb_name, plugin_namespace)`` scopes dedup per
knowledge base and plugin namespace.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.db import get_sync_conn
from eagle_rag.db.repositories.base import instance_namespace

__all__ = [
    "compute_sha256",
    "compute_sha256_bytes",
    "check_duplicate",
    "register",
    "check_and_register",
]

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


def _resolve_kb(kb_name: str | None) -> str:
    return kb_name if kb_name is not None else get_settings().kb_name


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "sha256": row[0],
        "kb_name": row[1],
        "plugin_namespace": row[2],
        "document_id": row[3],
        "object_key": row[4],
        "source_name": row[5],
        "created_at": row[6],
    }


_SELECT_SQL = (
    "SELECT sha256, kb_name, plugin_namespace, document_id, object_key, source_name, created_at "
    "FROM document_dedup WHERE sha256 = %s AND kb_name = %s AND plugin_namespace = %s"
)


def check_duplicate(
    sha256: str,
    kb_name: str | None = None,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    kb = _resolve_kb(kb_name)
    ns = instance_namespace(plugin_namespace)
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_SQL, (sha256, kb, ns))
            row = cur.fetchone()
    return _row_to_dict(row) if row is not None else None


def register(
    sha256: str,
    document_id: str,
    *,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    object_key: str | None = None,
    source_name: str | None = None,
) -> None:
    kb = _resolve_kb(kb_name)
    ns = instance_namespace(plugin_namespace)
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO document_dedup (sha256, kb_name, plugin_namespace, document_id, "
                "object_key, source_name) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (sha256, kb_name, plugin_namespace) DO NOTHING",
                (sha256, kb, ns, document_id, object_key, source_name),
            )


def check_and_register(
    file_path: str | Path,
    document_id: str,
    *,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    object_key: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    sha = compute_sha256(file_path)
    kb = _resolve_kb(kb_name)
    ns = instance_namespace(plugin_namespace)
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SELECT_SQL, (sha, kb, ns))
            row = cur.fetchone()
            if row is not None:
                result = _row_to_dict(row)
                result["hit"] = True
                return result
            cur.execute(
                "INSERT INTO document_dedup (sha256, kb_name, plugin_namespace, document_id, "
                "object_key, source_name) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (sha256, kb_name, plugin_namespace) DO NOTHING",
                (sha, kb, ns, document_id, object_key, source_name),
            )
            if cur.rowcount == 0:
                cur.execute(_SELECT_SQL, (sha, kb, ns))
                row = cur.fetchone()
                result = (
                    _row_to_dict(row)
                    if row is not None
                    else {
                        "sha256": sha,
                        "kb_name": kb,
                        "plugin_namespace": ns,
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
        "plugin_namespace": ns,
        "document_id": document_id,
        "object_key": object_key,
        "source_name": source_name,
        "created_at": None,
    }
