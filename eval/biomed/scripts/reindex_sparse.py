#!/usr/bin/env python3
"""Backfill biomed Milvus metadata for hybrid retrieval (primary_drugs)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def _collection_field_names(client: Any, collection: str) -> set[str]:
    try:
        desc = client.describe_collection(collection)
    except Exception:  # noqa: BLE001
        return set()
    fields = desc.get("fields") if isinstance(desc, dict) else None
    if fields is None and hasattr(desc, "fields"):
        fields = desc.fields
    names: set[str] = set()
    for field in fields or []:
        if isinstance(field, dict):
            name = field.get("name")
        else:
            name = getattr(field, "name", None)
        if name:
            names.add(str(name))
    return names


def _ensure_primary_drugs_field(client: Any, collection: str) -> bool:
    fields = _collection_field_names(client, collection)
    if "primary_drugs" in fields:
        return True
    try:
        from pymilvus import DataType

        client.add_collection_field(
            collection,
            field_name="primary_drugs",
            data_type=DataType.VARCHAR,
            max_length=2048,
            nullable=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"skip add primary_drugs on {collection}: {exc}")
        return False


_UPSERT_FIELDS = (
    "id",
    "vector",
    "text",
    "document_id",
    "kb_name",
    "path",
    "chunk_type",
    "source_type",
    "source_chunk_id",
    "primary_drugs",
)


def _row_for_upsert(row: dict[str, Any], primary_drugs: str) -> dict[str, Any]:
    """Build a full Milvus upsert row (partial upsert would wipe required fields)."""
    out = {key: row.get(key) for key in _UPSERT_FIELDS if key in row}
    out["primary_drugs"] = primary_drugs
    return out


def _infer_primary_drugs(document_name: str, text: str) -> str | None:
    from plugins.biomed.umls import match_drug_entities

    hits: list[str] = []
    hits.extend(match_drug_entities(document_name))
    hits.extend(match_drug_entities(text[:1024]))
    ordered: list[str] = []
    seen: set[str] = set()
    for item in hits:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    if not ordered:
        return None
    return json.dumps(ordered[:8], ensure_ascii=False)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument("--collection", default="eagle_text_biomed")
    ap.add_argument("--limit", type=int, default=0, help="Max rows to update (0 = all)")
    args = ap.parse_args()

    from eagle_rag.index.milvus_pool import get_milvus_pool
    from eagle_rag.index.registry import lookup_documents_sync
    from eagle_rag.plugins.milvus_ns import milvus_db_name

    db_name = milvus_db_name("biomed")
    client = get_milvus_pool().get(db_name)
    if not client.has_collection(args.collection):
        print(f"collection missing: {args.collection}")
        return 1

    if not _ensure_primary_drugs_field(client, args.collection):
        print("primary_drugs field unavailable; hybrid still uses query-time lexical fusion")
        return 0

    schema_fields = _collection_field_names(client, args.collection)
    output_fields = [f for f in _UPSERT_FIELDS if f in schema_fields]
    if "id" not in output_fields:
        output_fields = ["id", "text", "document_id", "vector"]

    expr = f'kb_name == "{args.kb_name}"'
    iterator = client.query_iterator(
        collection_name=args.collection,
        filter=expr,
        output_fields=output_fields,
        batch_size=100,
    )
    updated = 0
    scanned = 0
    while True:
        batch = iterator.next()
        if not batch:
            break
        doc_ids = [str(row.get("document_id") or "") for row in batch if row.get("document_id")]
        docs = lookup_documents_sync(doc_ids, plugin_namespace="biomed")
        upsert_rows: list[dict[str, Any]] = []
        for row in batch:
            scanned += 1
            if row.get("primary_drugs"):
                continue
            doc_id = str(row.get("document_id") or "")
            doc = docs.get(doc_id) or {}
            name = str(doc.get("name") or "")
            text = str(row.get("text") or "")
            payload = _infer_primary_drugs(name, text)
            if not payload:
                continue
            upsert_rows.append(_row_for_upsert(row, payload))
        if upsert_rows:
            client.upsert(collection_name=args.collection, data=upsert_rows)
            updated += len(upsert_rows)
        if args.limit and scanned >= args.limit:
            break

    print(f"scanned={scanned} updated_primary_drugs={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
