"""Biomed query-time retrieval intent detection."""

from __future__ import annotations

import re

from eagle_rag.plugins.routing import QueryRetrievalIntent
from plugins.biomed.umls import match_drug_entities

__all__ = ["detect_retrieval_intent"]

_COMPOUND_CUE_RE = re.compile(
    r"\b(smiles|inchi|compound|ligand|molecular\s+formula)\b",
    re.IGNORECASE,
)
_LABEL_CUE_RE = re.compile(
    r"\b(drug\s+label|prescribing\s+information|prescribing\s+info|"
    r"label\s+warning|indications?\s+and\s+usage|dosage\s+and\s+administration)\b",
    re.IGNORECASE,
)
_COMBINATION_CUE_RE = re.compile(
    r"\b(combination|combined\s+with|co-?administered|plus)\b",
    re.IGNORECASE,
)


def detect_retrieval_intent(query: str) -> QueryRetrievalIntent:
    """Infer biomed retrieval task from query text (never eval workflow labels)."""
    q = query or ""
    q_lower = q.lower()

    if _COMPOUND_CUE_RE.search(q):
        return QueryRetrievalIntent(
            workflow="chemical",
            suppress_collections=(),
            section_cues=("compound",),
            require_entity_match=True,
        )

    section_cues: list[str] = []
    if re.search(r"\bwarning", q_lower):
        section_cues.append("warnings")
    if re.search(r"\b(dosage|dosing)\b", q_lower):
        section_cues.append("dosage")

    if _LABEL_CUE_RE.search(q):
        if re.search(r"\b(indications?|usage)\b", q_lower):
            section_cues.append("indications_and_usage")
        return QueryRetrievalIntent(
            workflow="regulatory",
            suppress_collections=("eagle_chemical",),
            section_cues=tuple(section_cues or ("indications_and_usage",)),
            require_entity_match=True,
        )

    drugs = list(match_drug_entities(q))
    if _COMBINATION_CUE_RE.search(q) and len(drugs) >= 2:
        return QueryRetrievalIntent(
            workflow="combination",
            section_cues=tuple(section_cues),
            require_entity_match=True,
        )

    if drugs:
        return QueryRetrievalIntent(
            workflow="drug_entity",
            section_cues=tuple(section_cues),
            require_entity_match=True,
        )

    return QueryRetrievalIntent(workflow="general", section_cues=tuple(section_cues))
