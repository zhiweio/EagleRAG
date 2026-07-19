"""Biomed query-time retrieval intent detection."""

from __future__ import annotations

import re

from eagle_rag.plugins.routing import QueryRetrievalIntent

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
_INDICATIONS_RE = re.compile(
    r"\b(indications?|usage|prescribing|renal\s+cell\s+carcinoma|rcc)\b",
    re.IGNORECASE,
)


def detect_retrieval_intent(query: str) -> QueryRetrievalIntent:
    """Infer biomed retrieval workflow and collection/doc-type preferences."""
    q = query or ""
    q_lower = q.lower()

    if _COMPOUND_CUE_RE.search(q):
        return QueryRetrievalIntent(
            workflow="compound_match",
            prefer_doc_types=("compound",),
            section_cues=("compound",),
        )

    section_cues: list[str] = []
    if _INDICATIONS_RE.search(q):
        section_cues.append("indications_and_usage")
    if re.search(r"\bwarning", q_lower):
        section_cues.append("warnings")
    if re.search(r"\b(dosage|dosing)\b", q_lower):
        section_cues.append("dosage")

    if _LABEL_CUE_RE.search(q):
        return QueryRetrievalIntent(
            workflow="regulatory",
            prefer_doc_types=("drug_label",),
            suppress_collections=("eagle_chemical",),
            section_cues=tuple(section_cues or ("indications_and_usage",)),
        )

    if section_cues:
        return QueryRetrievalIntent(
            workflow="regulatory",
            prefer_doc_types=("drug_label", "research"),
            section_cues=tuple(section_cues),
        )

    return QueryRetrievalIntent()
