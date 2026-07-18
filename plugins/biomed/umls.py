"""Local UMLS-subset ontology helpers shared by routing, QUERY_ASSEMBLE, and MCP."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "expand_query_with_entities",
    "load_umls_index",
    "match_entities",
    "resolve_entity",
    "resolve_compound_query",
]

_RULES_PATH = Path(__file__).resolve().parent / "routing_rules.yaml"


@lru_cache(maxsize=1)
def load_umls_index() -> dict[str, Any]:
    with _RULES_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def match_entities(query: str) -> list[str]:
    """Return canonical entity keys matched in ``query`` (substring + keyword)."""
    rules = load_umls_index()
    hits: list[str] = []
    lowered = query.lower()
    for entity, meta in rules.get("umls_entities", {}).items():
        names = [entity, *list(meta.get("aliases", []) or [])]
        if any(str(name).lower() in lowered for name in names):
            hits.append(entity)
    for keyword in rules.get("entity_keywords", []):
        if re.search(rf"\b{re.escape(str(keyword))}\b", query, re.IGNORECASE):
            if str(keyword) not in hits:
                hits.append(str(keyword))
    return hits


def resolve_entity(entity: str) -> dict[str, Any]:
    """Resolve a single entity to aliases / pathways / related drugs."""
    rules = load_umls_index()
    umls = rules.get("umls_entities", {})
    key = next((k for k in umls if k.lower() == entity.strip().lower()), None)
    if key is None:
        # alias lookup
        for k, meta in umls.items():
            aliases = [str(a).lower() for a in (meta.get("aliases") or [])]
            if entity.strip().lower() in aliases:
                key = k
                break
    if key is None:
        return {
            "entity": entity,
            "found": False,
            "aliases": [],
            "pathways": [],
            "related_drugs": [],
        }
    meta = umls[key]
    return {
        "entity": key,
        "found": True,
        "cui": meta.get("cui"),
        "aliases": list(meta.get("aliases", []) or []),
        "pathways": list(meta.get("pathways", []) or []),
        "related_drugs": list(meta.get("related_drugs", []) or []),
    }


def expand_query_with_entities(query: str, *, limit: int = 8) -> str | None:
    """Return an expansion suffix for QUERY_ASSEMBLE, or None when nothing matched."""
    hits = match_entities(query)
    if not hits:
        return None
    aliases: list[str] = []
    for hit in hits[:limit]:
        resolved = resolve_entity(hit)
        if resolved.get("found"):
            aliases.extend(resolved.get("aliases", [])[:3])
            aliases.extend(resolved.get("pathways", [])[:2])
        else:
            aliases.append(hit)
    # de-dupe preserving order
    seen: set[str] = set()
    ordered: list[str] = []
    for item in aliases:
        low = item.lower()
        if low not in seen:
            seen.add(low)
            ordered.append(item)
    if not ordered:
        return None
    return f"[biomed entities: {', '.join(ordered[:limit])}]"


def resolve_compound_query(smiles_or_name: str) -> str:
    """Map a common compound name to SMILES when listed; otherwise return input."""
    rules = load_umls_index()
    chemical = rules.get("chemical", {}) if isinstance(rules.get("chemical"), dict) else {}
    aliases = (
        chemical.get("name_aliases", {}) if isinstance(chemical.get("name_aliases"), dict) else {}
    )
    key = smiles_or_name.strip().lower()
    if key in aliases:
        return str(aliases[key])
    return smiles_or_name.strip()
