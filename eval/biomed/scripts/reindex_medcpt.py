#!/usr/bin/env python3
"""Re-embed eagle_text_biomed rows into eagle_text_medcpt using MedCPT Article encoder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument("--source", default="eagle_text_biomed")
    ap.add_argument("--target", default="eagle_text_medcpt")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    from eagle_rag.index.milvus_pool import get_milvus_pool
    from eagle_rag.plugins.encoder_runtime import encode_text_for_encoder
    from eagle_rag.plugins.milvus_ns import milvus_db_name
    from plugins.biomed import ensure_biomed_collections
    from plugins.biomed.encoders import register_encoders
    from eagle_rag.plugins.context import PluginContext

    ctx = PluginContext(plugin_namespace="biomed")
    register_encoders(ctx)
    ensure_biomed_collections(ctx)

    db_name = milvus_db_name("biomed")
    client = get_milvus_pool().get(db_name)
    if not client.has_collection(args.source):
        print(f"source collection missing: {args.source}")
        return 1

    fields = [
        "id",
        "text",
        "document_id",
        "kb_name",
        "path",
        "chunk_type",
        "source_type",
        "source_chunk_id",
        "primary_drugs",
        "biomed_section",
    ]
    expr = f'kb_name == "{args.kb_name}"'
    iterator = client.query_iterator(
        collection_name=args.source,
        filter=expr,
        output_fields=fields,
        batch_size=32,
    )
    written = 0
    scanned = 0
    while True:
        batch = iterator.next()
        if not batch:
            break
        rows: list[dict[str, Any]] = []
        for row in batch:
            scanned += 1
            text = str(row.get("text") or "")
            if not text:
                continue
            vector = encode_text_for_encoder("medcpt-article", text)
            out = dict(row)
            out["vector"] = vector
            primary = out.get("primary_drugs")
            if isinstance(primary, list):
                out["primary_drugs"] = json.dumps(primary, ensure_ascii=False)
            rows.append(out)
        if rows:
            client.upsert(collection_name=args.target, data=rows)
            written += len(rows)
        if args.limit and scanned >= args.limit:
            break

    print(f"scanned={scanned} upserted={written} target={args.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
