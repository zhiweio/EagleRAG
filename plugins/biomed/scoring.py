"""Biomed entity and metadata scoring helpers (plugin-local; not in Core)."""

from __future__ import annotations

import json
from typing import Any

__all__ = ["entity_boost_score", "parse_primary_drugs"]


def parse_primary_drugs(metadata: dict[str, Any]) -> list[str]:
    """Parse ``primary_drugs`` from chunk metadata (list or JSON string)."""
    raw = metadata.get("primary_drugs")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        return [text]
    return []


def entity_boost_score(metadata: dict[str, Any], drug_entities: list[str]) -> float:
    """Soft boost when chunk metadata aligns with query drug entities."""
    if not drug_entities:
        return 0.0
    drugs_l = {d.lower() for d in drug_entities if d}
    for drug in parse_primary_drugs(metadata):
        if drug.lower() in drugs_l:
            return 1.0
    blob = " ".join(
        str(metadata.get(key) or "") for key in ("path", "file_name", "document_name", "source_uri")
    ).lower()
    if any(drug in blob for drug in drugs_l):
        return 0.5
    return 0.0
