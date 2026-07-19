"""Biomed query-side collection routing (G15/G20 UMLS + specialized collections)."""

from __future__ import annotations

import re
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.plugins.routing import CollectionQueryPlan, QueryRouteDecision
from plugins.biomed.umls import load_umls_index, match_drug_entities, match_entities, resolve_entity

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
    """Biomed query router: default dense biomedical index + optional general/hybrid plans."""

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
        plan_top_k = int(biomed_cfg.get("collection_recall_top_k", 20))
        mode = (route_mode or "text").lower()
        plans: dict[str, CollectionQueryPlan] = {}

        def add(collection: str, encoder: str, *, top_k: int = plan_top_k) -> None:
            plans[collection] = CollectionQueryPlan(
                collection=collection,
                encoder=encoder,
                top_k=top_k,
            )

        if mode in ("text", "hybrid"):
            add("eagle_text_biomed", "pubmedbert")
            if dual:
                add(settings.milvus.text_collection, "text-embedding-v4")

        umls_hits = self._match_umls(query)
        drug_hits = match_drug_entities(query)

        from plugins.biomed.query_intent import detect_retrieval_intent

        intent = detect_retrieval_intent(query)
        retrieval_hints: dict[str, Any] = {}
        if drug_hits or umls_hits:
            retrieval_hints["parent_doc_retrieval"] = False

        suppress_chemical = "eagle_chemical" in intent.suppress_collections
        if self._match_smiles(query) or (drug_hits and not suppress_chemical):
            add("eagle_chemical", "molformer")
        elif not suppress_chemical:
            for entity in umls_hits:
                related = resolve_entity(entity).get("related_drugs") or []
                if related and entity not in drug_hits:
                    add("eagle_chemical", "molformer")
                    break

        if self._match_keywords(query, "radiology"):
            add("eagle_medical_radiology", "medimageinsight")

        if self._match_keywords(query, "pathology"):
            add("eagle_medical_pathology", "uni2")

        if mode in ("visual", "hybrid") or has_image:
            add(settings.milvus.visual_collection, "qwen3-vl")

        for extra in exploratory:
            if extra == "eagle_text_biomed":
                add("eagle_text_biomed", "pubmedbert")
            elif extra == "eagle_text":
                add(settings.milvus.text_collection, "text-embedding-v4")
            elif extra == "eagle_chemical":
                add("eagle_chemical", "molformer")
            elif extra == "eagle_medical_radiology":
                add("eagle_medical_radiology", "medimageinsight")
            elif extra == "eagle_medical_pathology":
                add("eagle_medical_pathology", "uni2")

        if not plans:
            return None

        if len(plans) == 1 and not umls_hits and not drug_hits and not self._match_smiles(query):
            only = next(iter(plans.values()))
            if only.collection == settings.milvus.visual_collection:
                return QueryRouteDecision(
                    plans=tuple(plans.values()),
                    retrieval_hints=retrieval_hints,
                )

        return QueryRouteDecision(
            plans=tuple(plans.values()),
            retrieval_hints=retrieval_hints,
        )
