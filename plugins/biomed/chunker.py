"""Knowhere-preserving biomed section tagger (CHUNK enrich — not a chunker).

Structural parse (tree / TOC / typed chunks / ``path``) is **Knowhere-only**.
This module never re-splits text, never rewrites ``path`` / node body, and never
rebuilds ``doc_nav``. It only annotates existing Knowhere nodes with:

- ``metadata["biomed_section"]`` — IMRaD / patent aliases normalized from
  Knowhere ``path`` segments (``abstract`` / ``introduction`` / ``methods`` /
  ``results`` / ``discussion`` / ``conclusion`` / ``claims`` / ``body``)
- ``metadata["biomed_doc_type"]`` — ``research`` / ``patent`` / ``other``

Text-heading regex is a **last resort** when ``path`` is empty (flat dumps).
True boundary / hierarchy changes belong in Knowhere parse (upstream), not here.
"""

from __future__ import annotations

import re
from typing import Any

from eagle_rag.plugins.hookbus import HookContext
from eagle_rag.telemetry import get_logger

__all__ = ["biomed_chunk_transform", "detect_section", "detect_doc_type"]

logger = get_logger(__name__)

# Canonical IMRaD + conclusion + patent sections, lowercased.
_SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "abstract": ("abstract", "summary", "executive summary"),
    "introduction": ("introduction", "background", "1 introduction"),
    "methods": (
        "methods",
        "materials and methods",
        "methodology",
        "experimental methods",
        "materials",
    ),
    "results": ("results", "findings", "results and discussion"),
    "discussion": ("discussion", "conclusions and discussion"),
    "conclusion": ("conclusion", "conclusions", "concluding remarks"),
    "claims": ("claims", "what is claimed", "claim 1"),
}

# Heading regex: optional leading number ("3.", "3.1", "3.1.2") + section word.
_HEADING_NUM_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?"
    r"(?P<sec>[A-Za-z][A-Za-z \-]{2,60}?)\s*[:.\n\r]?\s*$"
)
# Patent claim markers.
_CLAIM_RE = re.compile(
    r"^\s*(?:claim\s+\d+|what\s+is\s+claimed|we\s+claim|1\.\s+A\s+)",
    re.IGNORECASE,
)
# All-caps short heading line (<= 6 words), e.g. "RESULTS", "MATERIALS AND METHODS".
_ALLCAPS_RE = re.compile(r"^\s*[A-Z][A-Z &/\-]{2,60}?\s*$")


def _normalize(segment: str) -> str:
    """Lowercase + collapse whitespace + strip numbering prefix."""
    s = segment.strip().lower()
    # Strip leading numbering like "3.1 " or "3 " from the segment.
    s = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", s)
    return re.sub(r"\s+", " ", s).strip(" .:")


def _match_section(normalized: str) -> str | None:
    """Map a normalized segment/heading to a canonical section, or None."""
    if not normalized:
        return None
    for canonical, aliases in _SECTION_ALIASES.items():
        for alias in aliases:
            if (
                normalized == alias
                or normalized.startswith(alias + " ")
                or normalized.startswith(alias + ":")
            ):
                return canonical
            # "materials and methods" may appear as "methods and materials"
            if " " in alias and alias in normalized:
                return canonical
    return None


def _section_from_path(path: str) -> str | None:
    """Walk Knowhere ``path`` leaf→root; first IMRaD/claims match wins."""
    if not path or not path.strip():
        return None
    segments = [_normalize(seg) for seg in path.split("/") if seg.strip()]
    for seg in reversed(segments):
        sec = _match_section(seg)
        if sec is not None:
            return sec
    return None


def _section_from_text_heading(text: str) -> str | None:
    """Weak fallback when Knowhere ``path`` is absent (not a re-chunker)."""
    first_line = ""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            first_line = stripped
            break
    if first_line:
        norm = _normalize(first_line)
        sec = _match_section(norm)
        if sec is not None:
            return sec
        if _CLAIM_RE.match(first_line):
            return "claims"
        m = _HEADING_NUM_RE.match(first_line)
        if m:
            sec = _match_section(_normalize(m.group("sec")))
            if sec is not None:
                return sec
        if _ALLCAPS_RE.match(first_line) and len(first_line.split()) <= 6:
            sec = _match_section(norm)
            if sec is not None:
                return sec

    head = (text or "")[:400]
    if _CLAIM_RE.search(head):
        return "claims"
    return None


def detect_section(path: str, text: str) -> str:
    """Return the canonical IMRaD/claims section for a chunk, or ``"body"``.

    Knowhere-first:

    1. Prefer ``path`` segments (doc_nav skeleton). If ``path`` is non-empty,
       never override with body-text heading heuristics — unmatched path →
       ``"body"``.
    2. Only when ``path`` is empty, fall back to a leading heading / claim
       marker scan (flat text dumps).
    """
    from_path = _section_from_path(path)
    if from_path is not None:
        return from_path
    if path and path.strip():
        return "body"
    from_text = _section_from_text_heading(text)
    return from_text if from_text is not None else "body"


def detect_doc_type(path: str, text: str) -> str:
    """Coarse document type: ``research`` / ``patent`` / ``other``.

    Uses structural signals (detected section + explicit claim/patent markers)
    rather than bare keyword presence, so a business memo mentioning "results"
    is not misclassified as research.
    """
    blob = ((path or "") + " " + (text or "")[:800]).lower()
    if "what is claimed" in blob or "we claim" in blob or "patent claim" in blob:
        return "patent"
    section = detect_section(path, text)
    if section in {
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "conclusion",
    }:
        return "research"
    if section == "claims":
        return "patent"
    return "other"


def _node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if isinstance(text, str) and text:
        return text
    get_content = getattr(node, "get_content", None)
    if callable(get_content):
        return str(get_content() or "")
    return ""


def _has_knowhere_structure(meta: dict[str, Any]) -> bool:
    path = str(meta.get("path") or "").strip()
    chunk_id = str(meta.get("chunk_id") or meta.get("source_chunk_id") or "").strip()
    return bool(path or chunk_id)


def biomed_chunk_transform(
    hook_ctx: HookContext,
    nodes: list[Any],
    **kwargs: object,
) -> list[Any]:
    """Annotate Knowhere text nodes with IMRaD section + doc-type metadata.

    ``CHUNK`` hook (``invoke_transform``): **enrich only**. Does not change
    node text, ``path``, or drop ``section_summary`` nodes. Feeds
    ``BiomedTextClassifier`` via ``ClassificationContext.extra["section"]``.
    """
    del kwargs
    out: list[Any] = []
    for node in nodes:
        meta = getattr(node, "metadata", None) or {}
        if not isinstance(meta, dict):
            out.append(node)
            continue

        original_path = str(meta.get("path") or "")
        original_text = _node_text(node)
        if not _has_knowhere_structure(meta):
            logger.warning(
                "biomed_chunk_transform: node lacks Knowhere path/chunk_id; "
                "annotating with text-fallback only (not a splitter) "
                "document_id=%s kb_name=%s",
                hook_ctx.document_id,
                hook_ctx.kb_name,
            )

        path_empty = not original_path.strip()
        section = detect_section(original_path, original_text)
        if path_empty and section != "body":
            logger.info(
                "biomed_chunk_transform: section from text-heading fallback "
                "(empty Knowhere path) biomed_section=%s document_id=%s",
                section,
                hook_ctx.document_id,
            )

        doc_type = detect_doc_type(original_path, original_text)
        meta = dict(meta)
        # Enrich only — do not rewrite path / body / Knowhere structure keys.
        meta["biomed_section"] = section
        meta["biomed_doc_type"] = doc_type
        node.metadata = meta
        out.append(node)
    return out
