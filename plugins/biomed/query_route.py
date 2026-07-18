"""Biomed query-side collection routing (G15/G20 rule + UMLS entity triggers)."""

from __future__ import annotations

import re
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.plugins.routing import CollectionQueryPlan, QueryRouteDecision
from plugins.biomed.umls import load_umls_index, match_entities

__all__ = ["BiomedQueryRouteClassifier", "_load_rules"]


def _load_rules() -> dict[str, Any]:
    return load_umls_index()


def _compile_patterns(rules: dict[str, Any]) -> dict[str, list[re.Pattern[str]]]:
    chemical = rules.get("chemical", {})
    patterns: list[re.Pattern[str]] = []
    for entry in chemical.get("smiles_patterns", []):
        if isinstance(entry, dict) and entry.get("pattern"):
            patterns.append(re.compile(str(entry["pattern"]), re.IGNORECASE))
    return {"smiles": patterns}


class BiomedQueryRouteClassifier:
    """Rule-based query router for biomed specialized collections."""

    def __init__(self) -> None:
        self._rules = _load_rules()
        self._patterns = _compile_patterns(self._rules)

    def _match_umls(self, query: str) -> list[str]:
        return match_entities(query)

    def _match_keywords(self, query: str, section: str) -> bool:
        items = self._rules.get(section, {})
        keywords = items.get("keywords", []) if isinstance(items, dict) else []
        return any(re.search(rf"\b{re.escape(str(kw))}\b", query, re.IGNORECASE) for kw in keywords)

    def _match_smiles(self, query: str) -> bool:
        if self._match_keywords(query, "chemical"):
            return True
        return any(p.search(query) for p in self._patterns["smiles"])

    def route(
        self,
        query: str,
        plugin_namespace: str,
        *,
        has_image: bool = False,
        route_mode: str = "text",
        scope_document_ids: tuple[str, ...] | None = None,
        scope_kb_names: tuple[str, ...] | None = None,
        scope_tags: tuple[str, ...] | None = None,
    ) -> QueryRouteDecision | None:
        del scope_document_ids, scope_kb_names, scope_tags  # scope-aware union wired in M3.5

        if plugin_namespace != "biomed":
            return None

        settings = get_settings()
        from eagle_rag.config import plugin_options

        biomed_cfg = plugin_options("biomed", settings)
        dual = bool(biomed_cfg.get("default_dual_text_search", False))
        exploratory = list(biomed_cfg.get("exploratory_search_collections") or [])
        mode = (route_mode or "text").lower()
        plans: dict[str, CollectionQueryPlan] = {}

        def add(collection: str, encoder: str, *, top_k: int = 5) -> None:
            plans[collection] = CollectionQueryPlan(
                collection=collection,
                encoder=encoder,
                top_k=top_k,
            )

        add(settings.milvus.text_collection, "text-embedding-v4")

        umls_hits = self._match_umls(query)
        if umls_hits or dual:
            add("eagle_text_biomed", "pubmedbert")

        if self._match_smiles(query):
            add("eagle_chemical", "molformer")

        if self._match_keywords(query, "radiology"):
            add("eagle_medical_radiology", "medimageinsight")

        if self._match_keywords(query, "pathology"):
            add("eagle_medical_pathology", "uni2")

        if mode in ("visual", "hybrid") or has_image:
            add(settings.milvus.visual_collection, "qwen3-vl")

        for extra in exploratory:
            if extra == "eagle_text_biomed":
                add("eagle_text_biomed", "pubmedbert")
            elif extra == "eagle_chemical":
                add("eagle_chemical", "molformer")
            elif extra == "eagle_medical_radiology":
                add("eagle_medical_radiology", "medimageinsight")
            elif extra == "eagle_medical_pathology":
                add("eagle_medical_pathology", "uni2")

        if not umls_hits and not dual:
            plans.pop("eagle_text_biomed", None)

        if len(plans) <= 1 and not umls_hits and not self._match_smiles(query):
            if not self._match_keywords(query, "radiology") and not self._match_keywords(
                query, "pathology"
            ):
                return None

        return QueryRouteDecision(plans=tuple(plans.values()))
