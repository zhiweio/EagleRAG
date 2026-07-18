"""Biomed ingest-route selector and PubMedBERT rerank hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eagle_rag.plugins.hookbus import HookContext

__all__ = ["biomed_format_selector", "biomed_rerank"]

_BIOMED_EXTS = {
    ".pdb",
    ".sdf",
    ".mol",
    ".mol2",
    ".cif",
    ".dcm",
    ".nii",
    ".nii.gz",
}


def biomed_format_selector(
    ctx: HookContext,
    *,
    file_path: str | None = None,
    file_name: str | None = None,
    source_type: str | None = None,
    **kwargs: object,
) -> str | None:
    """Route biomed-specific formats to the Core ``knowhere`` pipeline (G7)."""
    del kwargs, source_type
    name = file_name or file_path or ""
    suffix = Path(name).suffix.lower()
    if name.lower().endswith(".nii.gz"):
        suffix = ".nii.gz"
    if suffix in _BIOMED_EXTS:
        return "knowhere"
    return None


def biomed_rerank(
    ctx: HookContext,
    nodes: list[Any],
    *,
    query: str,
    collection: str | None = None,
    encoder: str | None = None,
    **kwargs: object,
) -> list[Any] | None:
    """Rerank ``eagle_text_biomed`` hits with PubMedBERT cosine similarity.

    Other collections abstain (return None) so Core qwen3-rerank can apply.
    """
    del kwargs
    coll = collection or (ctx.extra or {}).get("collection")
    enc = encoder or (ctx.extra or {}).get("encoder")
    if coll != "eagle_text_biomed" and enc != "pubmedbert":
        return None
    if not nodes:
        return nodes

    try:
        from eagle_rag.plugins.encoder_runtime import encode_text_for_encoder
    except Exception:  # noqa: BLE001
        return None

    try:
        q_vec = encode_text_for_encoder("pubmedbert", query)
    except Exception:  # noqa: BLE001
        return None

    scored: list[tuple[float, Any]] = []
    for node in nodes:
        text = ""
        if hasattr(node, "node"):
            text = getattr(node.node, "get_content", lambda: "")() or ""
            if not text:
                text = getattr(node.node, "text", "") or ""
        elif hasattr(node, "get_content"):
            text = node.get_content() or ""
        else:
            text = str(getattr(node, "text", "") or "")
        try:
            d_vec = encode_text_for_encoder("pubmedbert", text[:2048])
        except Exception:  # noqa: BLE001
            scored.append((getattr(node, "score", 0.0) or 0.0, node))
            continue
        # cosine (vectors are L2-normalized)
        score = sum(a * b for a, b in zip(q_vec, d_vec, strict=False))
        if hasattr(node, "score"):
            node.score = float(score)
        scored.append((float(score), node))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [node for _, node in scored]
