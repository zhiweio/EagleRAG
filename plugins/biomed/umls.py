"""Local UMLS-subset ontology helpers shared by routing, QUERY_ASSEMBLE, and MCP.

The curated subset (``routing_rules.yaml``) ships ~70 entities covering common
genes / proteins / drugs / diseases / pathways. For higher recall, point the
``EAGLE_BIOMED_UMLS_MRCONSO_PATH`` env var at a real UMLS MRCONSO RRF file
(requires an NLM UMLS Metathesaurus license); the loader merges additional
English (LAT=ENG) aliases and CUIs into the index. When the file is absent or
unreadable, only the curated subset is used (graceful, no error).
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "expand_query_for_dense_retrieval",
    "expand_query_with_entities",
    "load_umls_index",
    "load_umls_metathesaurus",
    "match_drug_entities",
    "match_entities",
    "resolve_entity",
    "resolve_compound_query",
]

_RULES_PATH = Path(__file__).resolve().parent / "routing_rules.yaml"
_MRCONSO_ENV = "EAGLE_BIOMED_UMLS_MRCONSO_PATH"
# MRCONSO columns (pipe-separated RRF). We only use the fields we need.
# CUI|LAT|TS|LUI|SAB|TTY|CODE|STR|SUI|ISPREF|...
_MRCONSO_CUI = 0
_MRCONSO_LAT = 1
_MRCONSO_STR = 7
_MRCONSO_ISPREF = 9

_DRUG_SUFFIX = re.compile(
    r"(?:mab|zumab|limab|nib|tinib|rafenib|citinib|parib|senib|stat|formin)$",
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def load_umls_index() -> dict[str, Any]:
    """Load the curated YAML entity index (the base for all matching)."""
    with _RULES_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data if isinstance(data, dict) else {}


def _normalize_alias(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


# Compiled regex cache for entity name boundary matching.
# Boundaries are letters only: a digit or hyphen adjacent to the match does not
# break it. This lets ``VEGFR`` match inside ``VEGFR1-3`` (trailing digit) while
# preventing ``EGFR`` from matching inside ``VEGFR`` (leading letter) and ``MET``
# from matching inside ``metastatic`` (trailing letter).
_ENTITY_BOUNDARY_CACHE: dict[str, re.Pattern[str]] = {}


def _entity_pattern(name: str) -> re.Pattern[str]:
    """Compile a case-insensitive, letter-boundary regex for ``name``."""
    cached = _ENTITY_BOUNDARY_CACHE.get(name)
    if cached is not None:
        return cached
    escaped = re.escape(name.lower())
    pattern = re.compile(rf"(?<![a-z]){escaped}(?![a-z])", re.IGNORECASE)
    _ENTITY_BOUNDARY_CACHE[name] = pattern
    return pattern


def load_umls_metathesaurus(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Parse a UMLS MRCONSO RRF file into ``{canonical_name: {aliases, cui}}``.

    Only English (LAT=ENG), preferred-term (ISPREF=Y) rows are kept. Returns an
    empty dict when the path is None / missing / unreadable so callers can use
    the curated subset alone. This is an enrichment layer, never a hard dep.

    The returned dict is keyed by a normalized canonical STR; values carry the
    CUI and the set of alias strings. Callers merge this into the curated index.
    """
    mrconso_path = Path(path or os.environ.get(_MRCONSO_ENV, "") or "")
    if not mrconso_path or not mrconso_path.is_file():
        return {}

    merged: dict[str, dict[str, Any]] = {}
    try:
        with mrconso_path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.rstrip("\n").split("|")
                if len(parts) <= _MRCONSO_ISPREF:
                    continue
                if parts[_MRCONSO_LAT] != "ENG":
                    continue
                if parts[_MRCONSO_ISPREF] != "Y":
                    continue
                cui = parts[_MRCONSO_CUI].strip()
                term = parts[_MRCONSO_STR].strip()
                if not term:
                    continue
                key = _normalize_alias(term)
                entry = merged.setdefault(
                    key,
                    {"canonical": term, "cui": cui, "aliases": set()},
                )
                if cui and not entry["cui"]:
                    entry["cui"] = cui
                entry["aliases"].add(term)
    except OSError:
        return {}

    # Convert sets to sorted lists for JSON-friendliness.
    for entry in merged.values():
        entry["aliases"] = sorted(entry["aliases"])
    return merged


@lru_cache(maxsize=1)
def _merged_index() -> dict[str, Any]:
    """Curated YAML base, augmented with MRCONSO aliases/CUIs when available."""
    base = load_umls_index()
    entities: dict[str, Any] = dict(base.get("umls_entities", {}) or {})

    mrconso = load_umls_metathesaurus()
    if mrconso:
        # Merge MRCONSO aliases into existing curated entities (by normalized
        # canonical name match), and add new entities not already present.
        for norm_key, entry in mrconso.items():
            # Find a curated entity whose canonical or alias matches this MRCONSO term.
            matched_key: str | None = None
            for cur_key, cur_meta in entities.items():
                cur_names = [cur_key, *(cur_meta.get("aliases") or [])]
                if norm_key in {_normalize_alias(n) for n in cur_names}:
                    matched_key = cur_key
                    break
            if matched_key is not None:
                meta = entities[matched_key]
                existing = set(_normalize_alias(a) for a in (meta.get("aliases") or []))
                for alias in entry["aliases"]:
                    if _normalize_alias(alias) not in existing:
                        meta.setdefault("aliases", []).append(alias)
                        existing.add(_normalize_alias(alias))
                if not meta.get("cui") and entry.get("cui"):
                    meta["cui"] = entry["cui"]
            else:
                entities[entry["canonical"]] = {
                    "aliases": entry["aliases"],
                    "cui": entry.get("cui", ""),
                    "pathways": [],
                    "related_drugs": [],
                }

    base["umls_entities"] = entities
    return base


def match_entities(query: str) -> list[str]:
    """Return canonical entity keys matched in ``query`` (letter-boundary match).

    Entity names and aliases are matched with letter-only boundaries so that
    ``EGFR`` does not fire on ``VEGFR`` and ``MET`` does not fire on
    ``metastatic``. Digits and hyphens are not boundaries, so ``VEGFR`` still
    matches inside ``VEGFR1-3`` and ``PD-1`` matches intact.
    """
    rules = _merged_index()
    hits: list[str] = []
    for entity, meta in rules.get("umls_entities", {}).items():
        names = [entity, *list(meta.get("aliases", []) or [])]
        if any(_entity_pattern(str(name)).search(query) for name in names):
            hits.append(entity)
    for keyword in rules.get("entity_keywords", []):
        if re.search(rf"\b{re.escape(str(keyword))}\b", query, re.IGNORECASE):
            if str(keyword) not in hits:
                hits.append(str(keyword))
    return hits


@lru_cache(maxsize=1)
def _drug_entity_keys() -> frozenset[str]:
    """Curated drug names for chemical-collection routing and entity boost."""
    rules = _merged_index()
    keys: set[str] = set()
    chemical = rules.get("chemical", {})
    aliases = chemical.get("name_aliases", {}) if isinstance(chemical, dict) else {}
    if isinstance(aliases, dict):
        keys.update(str(name).lower() for name in aliases)
    for entity, meta in (rules.get("umls_entities", {}) or {}).items():
        if not isinstance(meta, dict):
            continue
        if meta.get("entity_type") == "drug":
            keys.add(str(entity).lower())
            continue
        if _DRUG_SUFFIX.search(str(entity)):
            keys.add(str(entity).lower())
    return frozenset(keys)


def match_drug_entities(query: str) -> list[str]:
    """Return drug entity keys matched in ``query`` (subset of ``match_entities``)."""
    drug_keys = _drug_entity_keys()
    return [hit for hit in match_entities(query) if hit.lower() in drug_keys]


def resolve_entity(entity: str) -> dict[str, Any]:
    """Resolve a single entity to aliases / pathways / related drugs."""
    rules = _merged_index()
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


def expand_query_with_entities(query: str, *, limit: int = 12) -> str | None:
    """Return an expansion suffix for QUERY_ASSEMBLE, or None when nothing matched.

    Hits are ordered by their first occurrence in ``query`` so that entities the
    user actually mentioned take precedence over coincidental alias matches.
    Aliases/pathways per entity are capped (2 aliases, 1 pathway) to avoid
    diluting the query embedding with loosely related terms.
    """
    hits = match_entities(query)
    if not hits:
        return None

    # Rank hits by first occurrence in the query; unmatched-position entities
    # sort last while preserving discovery order.
    lowered = query.lower()

    def _hit_position(entity: str) -> int:
        rules = _merged_index()
        meta = rules.get("umls_entities", {}).get(entity, {})
        names = [entity, *list(meta.get("aliases", []) or [])]
        positions = [
            lowered.find(str(name).lower())
            for name in names
            if lowered.find(str(name).lower()) != -1
        ]
        return min(positions) if positions else len(lowered)

    hits.sort(key=_hit_position)

    aliases: list[str] = []
    for hit in hits[:limit]:
        resolved = resolve_entity(hit)
        if resolved.get("found"):
            aliases.extend(resolved.get("aliases", [])[:2])
            aliases.extend(resolved.get("pathways", [])[:1])
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


def expand_query_for_dense_retrieval(query: str) -> str | None:
    """Append UMLS aliases for dense embedding only (sparse keeps the raw query)."""
    suffix = expand_query_with_entities(query)
    if not suffix:
        return None
    return f"{query} {suffix}"


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
