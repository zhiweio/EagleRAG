"""Milvus visual vector collection wrapper (PixelRAG Tile vectors).

Manages the visual collection directly via ``pymilvus.MilvusClient`` (not
llama-index), because the visual vectors are 2048-dim Tile embeddings produced
by PixelRAG's external ``pixelrag_embed`` (Qwen3-VL-Embedding-2B), not a
LlamaIndex-standard embed_model. Provides idempotent schema creation, single/
batch upsert, hybrid search (vector similarity + scalar boolean filtering),
per-document deletion, and counting. All connections are created inside
functions; no Milvus connection at module import time.

Vector index uses Milvus built-in HNSW (default) or DiskANN (switchable for
large scale) instead of PixelRAG's native FAISS, configured via
``settings.milvus.visual_index_type``. Inverted indexes are built on the
``kb_name`` / ``document_id`` / ``source_type`` / ``year`` scalar fields to
accelerate filtering, supporting ``kb_name`` multi-tenant isolation and
hybrid search.

The dual-collection unification of the single Milvus cluster is surfaced at
the retriever layer (both text and visual retrievers return LlamaIndex nodes);
the visual collection remains managed directly by pymilvus due to the
embed_model difference.

Collection schema::

    id           VARCHAR(64) PK   -- image_id, identical to the image_id field
    vector       FLOAT_VECTOR dim=settings.milvus.dim_visual (2048)
    image_path   VARCHAR(512)     -- MinIO object_key or local path
    image_id     VARCHAR(64)      -- same as PK, for scalar filtering
    document_id  VARCHAR(64)
    page         INT64 (nullable)
    position     VARCHAR(64) (nullable)  -- e.g. "strip_3"
    kb_name      VARCHAR(64)      -- knowledge-base identifier (multi-tenant), default 'default'
    year         INT64 (nullable) -- document year
    source_type  VARCHAR(32) (nullable)  -- source type: policy/financial/...

The vector field is indexed with HNSW (M=16, efConstruction=256) or DiskANN
(metric_type=IP, inner product).
"""

from __future__ import annotations

import logging
from typing import Any

from pymilvus import DataType, MilvusClient

from eagle_rag.config import get_settings
from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.plugins.milvus_ns import milvus_db_name

logger = logging.getLogger(__name__)

__all__ = [
    "ensure_collection",
    "get_visual_client",
    "upsert_visual",
    "upsert_visual_batch",
    "search_visual",
    "delete_visual_by_document",
    "delete_visual_by_kb",
    "count_visual",
    "distinct_years",
    "fetch_visual_by_document",
]

# Legacy singleton removed (G24): use MilvusClientPool per db_name.
_client_db: str | None = None


def _uri() -> str:
    cfg = get_settings().milvus
    return f"http://{cfg.host}:{cfg.port}"


def _collection_name() -> str:
    return get_settings().milvus.visual_collection


def get_visual_client(plugin_namespace: str | None = None) -> MilvusClient:
    """Return a pooled MilvusClient bound to the namespace database."""
    global _client_db  # noqa: PLW0603
    db_name = milvus_db_name(plugin_namespace)
    if _client_db != db_name:
        ensure_collection(plugin_namespace=plugin_namespace)
        _client_db = db_name
    return get_milvus_pool().get(db_name)


def _vector_index_params(index_type: str) -> dict[str, Any]:
    """Return vector-field index params by index type (HNSW / DiskANN, metric_type=IP)."""
    idx = index_type.lower()
    if idx == "diskann":
        return {
            "index_type": "DISKANN",
            "metric_type": "IP",
            "params": {},
        }
    # Default to HNSW.
    return {
        "index_type": "HNSW",
        "metric_type": "IP",
        "params": {"M": 16, "efConstruction": 256},
    }


def _search_params(index_type: str) -> dict[str, Any]:
    """Return search params by index type (HNSW uses ef; DiskANN has no extra params)."""
    idx = index_type.lower()
    if idx == "diskann":
        return {"metric_type": "IP", "params": {}}
    return {"metric_type": "IP", "params": {"ef": 64}}


def ensure_collection(plugin_namespace: str | None = None) -> None:
    """Idempotently create the collection + indexes and load it. Reads ``settings.milvus``.

    - Index type follows ``visual_index_type``: HNSW (default) or DiskANN.
    - Builds Inverted indexes on ``kb_name`` / ``document_id`` / ``source_type`` /
      ``year`` to accelerate scalar filtering (try/except tolerates old Milvus).
    - Migration: if an existing legacy collection lacks the ``kb_name`` field
      (Milvus does not support ALTER ADD FIELD), drop and recreate it.
    """
    global _client_db  # noqa: PLW0603
    db_name = milvus_db_name(plugin_namespace)
    client = get_milvus_pool().get(db_name)
    _client_db = db_name

    cfg = get_settings().milvus
    coll_name = cfg.visual_collection
    dim = cfg.dim_visual
    index_type = cfg.visual_index_type

    # Migration: legacy collection missing kb_name is dropped and recreated.
    if client.has_collection(coll_name):
        desc = client.describe_collection(coll_name)
        field_names = {f["name"] for f in desc["fields"]}
        if "kb_name" not in field_names:
            client.drop_collection(coll_name)

    freshly_created = False
    if not client.has_collection(coll_name):
        schema = client.create_schema()
        schema.add_field("id", DataType.VARCHAR, max_length=64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
        schema.add_field("image_path", DataType.VARCHAR, max_length=512)
        schema.add_field("image_id", DataType.VARCHAR, max_length=64)
        schema.add_field("document_id", DataType.VARCHAR, max_length=64)
        schema.add_field("page", DataType.INT64, nullable=True)
        schema.add_field("position", DataType.VARCHAR, max_length=64, nullable=True)
        schema.add_field(
            "kb_name",
            DataType.VARCHAR,
            max_length=64,
            default_value="default",
        )
        schema.add_field("year", DataType.INT64, nullable=True)
        schema.add_field("source_type", DataType.VARCHAR, max_length=32, nullable=True)
        schema.add_field("chunk_type", DataType.VARCHAR, max_length=16, default_value="tile")
        schema.add_field("parent_section", DataType.VARCHAR, max_length=512, nullable=True)
        schema.add_field("content_summary", DataType.VARCHAR, max_length=2048, nullable=True)
        schema.add_field("source_chunk_id", DataType.VARCHAR, max_length=128, nullable=True)

        # Vector + scalar Inverted indexes are built together with the collection:
        # when index_params is passed, create_collection auto-builds indexes and
        # loads it, so no separate create_index / load is needed.
        idx_cfg = _vector_index_params(index_type)
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type=idx_cfg["index_type"],
            metric_type=idx_cfg["metric_type"],
            params=idx_cfg["params"],
        )
        for field_name in (
            "kb_name",
            "document_id",
            "source_type",
            "year",
            "chunk_type",
            "parent_section",
        ):
            index_params.add_index(field_name=field_name, index_type="INVERTED")
        client.create_collection(coll_name, schema=schema, index_params=index_params)
        freshly_created = True

    if not freshly_created:
        # Existing collection: release first, then backfill missing scalar Inverted indexes.
        # If on-disk indexes differ from the in-memory loaded set (e.g. new scalar
        # indexes were added without reload), a direct load_collection would raise
        # "can't change the index for loaded collection".
        try:
            client.release_collection(coll_name)
        except Exception:  # noqa: BLE001
            pass
        for field_name in ("kb_name", "document_id", "source_type", "year"):
            try:
                scalar_params = client.prepare_index_params()
                scalar_params.add_index(field_name=field_name, index_type="INVERTED")
                client.create_index(coll_name, scalar_params)
            except Exception:  # noqa: BLE001
                pass

        # Migration: incrementally add new scalar fields (without drop+recreate)
        # to backfill old collections missing them.
        desc = client.describe_collection(coll_name)
        field_names = {f["name"] for f in desc["fields"]}
        new_field_specs = [
            (
                "chunk_type",
                dict(
                    data_type=DataType.VARCHAR,
                    max_length=16,
                    nullable=True,
                    default_value="tile",
                ),
            ),
            (
                "parent_section",
                dict(data_type=DataType.VARCHAR, max_length=512, nullable=True),
            ),
            (
                "content_summary",
                dict(data_type=DataType.VARCHAR, max_length=2048, nullable=True),
            ),
            (
                "source_chunk_id",
                dict(data_type=DataType.VARCHAR, max_length=128, nullable=True),
            ),
        ]
        for field_name, kwargs in new_field_specs:
            if field_name in field_names:
                continue
            try:
                client.add_collection_field(coll_name, field_name=field_name, **kwargs)
            except Exception:  # noqa: BLE001
                logger.exception("add_collection_field failed: %s", field_name)

        # Backfill Inverted indexes on new fields (same try/except pattern as above).
        for field_name in ("chunk_type", "parent_section"):
            try:
                scalar_params = client.prepare_index_params()
                scalar_params.add_index(field_name=field_name, index_type="INVERTED")
                client.create_index(coll_name, scalar_params)
            except Exception:  # noqa: BLE001
                pass

    # Search requires the collection to be loaded; create_collection already
    # auto-loads when freshly created, so this call is idempotent.
    try:
        client.load_collection(coll_name)
    except Exception:  # noqa: BLE001
        pass


def _build_row(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize adapter input into a Milvus row dict (keyed by column name).

    ``kb_name`` falls back to ``settings.kb_name`` when missing;
    ``year`` / ``source_type`` default to None.
    """
    kb_name = item.get("kb_name")
    if kb_name is None:
        kb_name = get_settings().kb_name
    return {
        "id": item["image_id"],
        "vector": item["vector"],
        "image_path": item["image_path"],
        "image_id": item["image_id"],
        "document_id": item["document_id"],
        "page": item.get("page"),
        "position": item.get("position"),
        "kb_name": kb_name,
        "year": item.get("year"),
        "source_type": item.get("source_type"),
        "chunk_type": item.get("chunk_type") or "tile",
        "parent_section": item.get("parent_section"),
        "content_summary": item.get("content_summary"),
        "source_chunk_id": item.get("source_chunk_id"),
    }


def upsert_visual(
    *,
    image_id: str,
    vector: list[float],
    image_path: str,
    document_id: str,
    page: int | None = None,
    position: str | None = None,
    kb_name: str | None = None,
    year: int | None = None,
    source_type: str | None = None,
    chunk_type: str | None = None,
    parent_section: str | None = None,
    content_summary: str | None = None,
    source_chunk_id: str | None = None,
    plugin_namespace: str | None = None,
) -> None:
    """Upsert one visual vector record (overwrites by PK ``id``).

    ``kb_name`` falls back to ``settings.kb_name`` when None.
    """
    upsert_visual_batch(
        [
            {
                "image_id": image_id,
                "vector": vector,
                "image_path": image_path,
                "document_id": document_id,
                "page": page,
                "position": position,
                "kb_name": kb_name,
                "year": year,
                "source_type": source_type,
                "chunk_type": chunk_type,
                "parent_section": parent_section,
                "content_summary": content_summary,
                "source_chunk_id": source_chunk_id,
            }
        ],
        plugin_namespace=plugin_namespace,
    )


def upsert_visual_batch(
    items: list[dict[str, Any]],
    *,
    plugin_namespace: str | None = None,
) -> None:
    """Batch upsert.

    Each item contains image_id/vector/image_path/document_id/page/position
    plus optional kb_name (defaults to settings.kb_name) / year / source_type.
    """
    if not items:
        return
    client = get_visual_client(plugin_namespace)
    rows = [_build_row(it) for it in items]
    client.upsert(collection_name=_collection_name(), data=rows)


def _quote_in_list(values: list[str]) -> str:
    """Render a Milvus ``in [...]`` list of string literals with escaped quotes."""
    return "[" + ", ".join('"' + str(v).replace('"', '\\"') + '"' for v in values) + "]"


def _build_search_expr(
    *,
    document_id: str | None,
    kb_name: str | None,
    year: int | list[int] | None,
    source_type: str | None,
    parent_section: str | None = None,
    chunk_type: str | None = None,
    source_chunk_id: str | None = None,
    kb_names: list[str] | None = None,
    document_ids: list[str] | None = None,
) -> str | None:
    """Build a boolean expression from per-field filters, joined by ``and``.

    ``year`` as int produces ``year == 2025``; as list produces
    ``year in [2025, 2026]``. ``parent_section`` uses LIKE substring matching;
    ``chunk_type`` / ``source_chunk_id`` use exact match. When ``kb_names`` or
    ``document_ids`` are set, they form a union (OR) scope group
    ``(kb_name in [...] or document_id in [...])`` combined with the remaining
    filters via ``and``; this takes precedence over the single ``kb_name`` /
    ``document_id`` predicates. Returns None when no filters are set.
    """
    conditions: list[str] = []
    if kb_names or document_ids:
        scope_parts: list[str] = []
        if kb_names:
            scope_parts.append(f"kb_name in {_quote_in_list(kb_names)}")
        if document_ids:
            scope_parts.append(f"document_id in {_quote_in_list(document_ids)}")
        conditions.append(
            scope_parts[0] if len(scope_parts) == 1 else "(" + " or ".join(scope_parts) + ")"
        )
    else:
        if document_id is not None:
            conditions.append(f'document_id == "{document_id}"')
        if kb_name is not None:
            conditions.append(f'kb_name == "{kb_name}"')
    if source_type is not None:
        conditions.append(f'source_type == "{source_type}"')
    if parent_section is not None:
        conditions.append(f'parent_section like "%{parent_section}%"')
    if chunk_type is not None:
        conditions.append(f'chunk_type == "{chunk_type}"')
    if source_chunk_id is not None:
        conditions.append(f'source_chunk_id == "{source_chunk_id}"')
    if year is not None:
        if isinstance(year, list):
            joined = ", ".join(str(y) for y in year)
            conditions.append(f"year in [{joined}]")
        else:
            conditions.append(f"year == {year}")
    if not conditions:
        return None
    return " and ".join(conditions)


def search_visual(
    query_vector: list[float],
    *,
    top_k: int = 5,
    document_id: str | None = None,
    kb_name: str | None = None,
    year: int | list[int] | None = None,
    source_type: str | None = None,
    parent_section: str | None = None,
    chunk_type: str | None = None,
    source_chunk_id: str | None = None,
    kb_names: list[str] | None = None,
    document_ids: list[str] | None = None,
    expr: str | None = None,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search: vector similarity + scalar boolean filtering, returns Top-K.

    - If ``expr`` is provided, it is used directly as the scalar filter
      expression (highest priority, overrides per-field filters).
    - Otherwise a boolean expression is built from ``document_id`` / ``kb_name`` /
      ``year`` / ``source_type`` / ``parent_section`` / ``chunk_type`` /
      ``source_chunk_id``.
    - Search params are chosen by ``visual_index_type`` (HNSW uses ef; DiskANN
      has no extra params).
    - ``plugin_namespace`` binds the Milvus client to the namespace's Database
      (G17); no ``plugin_namespace`` scalar filter is added (DB-level isolation).

    Returns ``[{"image_id":..., "image_path":..., "document_id":..., "page":...,
    "position":..., "kb_name":..., "year":..., "source_type":...,
    "chunk_type":..., "parent_section":..., "content_summary":...,
    "source_chunk_id":..., "score":...}]``.
    """
    client = get_visual_client(plugin_namespace=plugin_namespace)
    coll_name = _collection_name()
    if expr is None:
        expr = _build_search_expr(
            document_id=document_id,
            kb_name=kb_name,
            year=year,
            source_type=source_type,
            parent_section=parent_section,
            chunk_type=chunk_type,
            source_chunk_id=source_chunk_id,
            kb_names=kb_names,
            document_ids=document_ids,
        )
    index_type = get_settings().milvus.visual_index_type
    results = client.search(
        collection_name=coll_name,
        data=[query_vector],
        anns_field="vector",
        search_params=_search_params(index_type),
        limit=top_k,
        filter=expr or "",
        output_fields=[
            "image_id",
            "image_path",
            "document_id",
            "page",
            "position",
            "kb_name",
            "year",
            "source_type",
            "chunk_type",
            "parent_section",
            "content_summary",
            "source_chunk_id",
        ],
    )
    out: list[dict[str, Any]] = []
    if not results:
        return out
    for hit in results[0]:
        entity = hit.get("entity", {})
        out.append(
            {
                "image_id": entity.get("image_id"),
                "image_path": entity.get("image_path"),
                "document_id": entity.get("document_id"),
                "page": entity.get("page"),
                "position": entity.get("position"),
                "kb_name": entity.get("kb_name"),
                "year": entity.get("year"),
                "source_type": entity.get("source_type"),
                "chunk_type": entity.get("chunk_type"),
                "parent_section": entity.get("parent_section"),
                "content_summary": entity.get("content_summary"),
                "source_chunk_id": entity.get("source_chunk_id"),
                "score": hit.get("distance"),
            }
        )
    return out


def delete_visual_by_document(document_id: str, *, plugin_namespace: str | None = None) -> int:
    """Delete all visual vectors of a document and return the deleted count."""
    client = get_visual_client(plugin_namespace=plugin_namespace)
    coll_name = _collection_name()
    expr = f'document_id == "{document_id}"'
    existing = client.query(coll_name, filter=expr, output_fields=["image_id"])
    count = len(existing)
    if count > 0:
        client.delete(coll_name, filter=expr)
    return count


def count_visual(
    document_id: str | None = None,
    *,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
) -> int:
    """Count visual vectors.

    - When both ``document_id`` and ``kb_name`` are None, returns the
      approximate total row count of the collection.
    - When either is given, returns an exact count via scalar filtering.
    """
    client = get_visual_client(plugin_namespace=plugin_namespace)
    coll_name = _collection_name()
    conditions: list[str] = []
    if document_id is not None:
        conditions.append(f'document_id == "{document_id}"')
    if kb_name is not None:
        conditions.append(f'kb_name == "{kb_name}"')
    if not conditions:
        stats = client.get_collection_stats(coll_name)
        return int(stats.get("row_count", 0))
    expr = " and ".join(conditions)
    rows = client.query(coll_name, filter=expr, output_fields=["image_id"])
    return len(rows)


def fetch_visual_by_document(
    document_id: str, *, limit: int = 4096, plugin_namespace: str | None = None
) -> list[dict[str, Any]]:
    """Fetch a document's visual tile records (scalar fields only, no vectors).

    Used to anchor visual tiles onto the document's parsed structure via
    ``parent_section`` / ``source_chunk_id``. Returns an empty list on failure.
    """
    client = get_visual_client(plugin_namespace=plugin_namespace)
    coll_name = _collection_name()
    safe_id = document_id.replace('"', '\\"')
    expr = f'document_id == "{safe_id}"'
    try:
        rows = client.query(
            coll_name,
            filter=expr,
            output_fields=[
                "image_id",
                "image_path",
                "document_id",
                "page",
                "position",
                "kb_name",
                "year",
                "source_type",
                "chunk_type",
                "parent_section",
                "content_summary",
                "source_chunk_id",
            ],
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_visual_by_document failed doc=%s: %s", document_id, exc)
        return []
    return list(rows)


def delete_visual_by_kb(kb_name: str, *, plugin_namespace: str | None = None) -> int:
    """Delete visual vectors by kb_name."""
    client = get_visual_client(plugin_namespace=plugin_namespace)
    coll_name = _collection_name()
    expr = f'kb_name == "{kb_name}"'
    existing = client.query(coll_name, filter=expr, output_fields=["image_id"])
    count = len(existing)
    if count > 0:
        client.delete(coll_name, filter=expr)
    return count


def distinct_years(*, kb_name: str | None = None, plugin_namespace: str | None = None) -> list[int]:
    """Return the list of distinct years in the visual collection."""
    client = get_visual_client(plugin_namespace=plugin_namespace)
    coll_name = _collection_name()
    expr = f'kb_name == "{kb_name}"' if kb_name else "year >= 0"
    try:
        rows = client.query(coll_name, filter=expr, output_fields=["year"], limit=16384)
    except Exception:  # noqa: BLE001
        return []
    years: set[int] = set()
    for r in rows:
        y = r.get("year")
        if y is not None:
            try:
                years.add(int(y))
            except (TypeError, ValueError):
                pass
    return sorted(years)
