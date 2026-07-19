#!/usr/bin/env python3
"""Backfill biomed Milvus biomed_section metadata from Knowhere path/text."""

from __future__ import annotations

import argparse
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


def _ensure_biomed_section_field(client: Any, collection: str) -> bool:
    fields = _collection_field_names(client, collection)
    if "biomed_section" in fields:
        return True
    try:
        from pymilvus import DataType

        client.add_collection_field(
            collection,
            field_name="biomed_section",
            data_type=DataType.VARCHAR,
            max_length=64,
            nullable=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"skip add biomed_section on {collection}: {exc}")
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
    "biomed_section",
)


def _row_for_upsert(row: dict[str, Any], biomed_section: str) -> dict[str, Any]:
    out = {key: row.get(key) for key in _UPSERT_FIELDS if key in row}
    out["biomed_section"] = biomed_section
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument("--collection", default="eagle_text_biomed")
    ap.add_argument("--limit", type=int, default=0, help="Max rows to update (0 = all)")
    args = ap.parse_args()

    from plugins.biomed.chunker import detect_section

    from eagle_rag.index.milvus_pool import get_milvus_pool
    from eagle_rag.plugins.milvus_ns import milvus_db_name

    db_name = milvus_db_name("biomed")
    client = get_milvus_pool().get(db_name)
    if not client.has_collection(args.collection):
        print(f"collection missing: {args.collection}")
        return 1

    if not _ensure_biomed_section_field(client, args.collection):
        print("biomed_section field unavailable")
        return 0

    schema_fields = _collection_field_names(client, args.collection)
    output_fields = [f for f in _UPSERT_FIELDS if f in schema_fields]
    if "id" not in output_fields:
        output_fields = ["id", "text", "document_id", "vector", "path"]

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
        upsert_rows: list[dict[str, Any]] = []
        for row in batch:
            scanned += 1
            if row.get("biomed_section"):
                continue
            path = str(row.get("path") or "")
            text = str(row.get("text") or "")
            section = detect_section(path, text)
            if not section or section == "body":
                continue
            upsert_rows.append(_row_for_upsert(row, section))
        if upsert_rows:
            client.upsert(collection_name=args.collection, data=upsert_rows)
            updated += len(upsert_rows)
        if args.limit and scanned >= args.limit:
            break

    print(f"scanned={scanned} updated_biomed_section={updated}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
