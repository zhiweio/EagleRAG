"""Tiered Document Router (TDR) — semantic document profile for encoder selection."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from eagle_rag.config import get_settings, plugin_options
from eagle_rag.telemetry import get_logger
from plugins.biomed.umls import match_entities

__all__ = [
    "DocumentTextProfile",
    "apply_text_profile_to_nodes",
    "build_document_sketch",
    "classify_document_text_profile",
    "clear_prototype_cache",
]

logger = get_logger(__name__)

TextProfile = Literal["biomedical", "general"]

_DEFAULT_PROTOTYPE_PATH = Path(__file__).resolve().parent / "doc_profile_prototypes.yaml"
_IMRAD_SECTIONS = frozenset(
    {
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "conclusion",
        "claims",
    }
)
_EMBED_DIM = 768


@dataclass(frozen=True)
class DocumentTextProfile:
    """Document-level encoder routing decision."""

    profile: TextProfile
    confidence: float
    rule: str
    tier: str
    signals: dict[str, float] = field(default_factory=dict)


def clear_prototype_cache() -> None:
    """Invalidate cached prototype vectors (tests)."""
    _load_prototype_vectors.cache_clear()


def _router_cfg() -> dict[str, Any]:
    biomed = plugin_options("biomed", get_settings())
    cfg = biomed.get("doc_semantic_router")
    return cfg if isinstance(cfg, dict) else {}


def _node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if isinstance(text, str) and text.strip():
        return text
    get_content = getattr(node, "get_content", None)
    if callable(get_content):
        return str(get_content() or "")
    return ""


def build_document_sketch(nodes: list[Any], *, max_chars: int = 8000) -> str:
    """Build a single document sketch for classification (no regex filtering)."""
    if not nodes:
        return ""

    parts: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        cleaned = re.sub(r"\s+", " ", (text or "").strip())
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        parts.append(cleaned)

    for node in nodes:
        meta = getattr(node, "metadata", None) or {}
        if not isinstance(meta, dict):
            continue
        chunk_type = str(meta.get("type") or meta.get("chunk_type") or "").lower()
        if chunk_type == "section_summary":
            _add(_node_text(node))
        summary = meta.get("content_summary")
        if isinstance(summary, str):
            _add(summary)

    for node in nodes[:8]:
        _add(_node_text(node))

    sketch = "\n\n".join(parts)
    if len(sketch) > max_chars:
        return sketch[:max_chars]
    return sketch


def _sketch_entropy(text: str) -> float:
    if not text:
        return 0.0
    tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff]+", text.lower())
    if len(tokens) < 8:
        return 0.0
    counts = Counter(tokens)
    total = float(len(tokens))
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
    return min(1.0, entropy / 5.0)


def _imrad_diversity(nodes: list[Any]) -> float:
    sections: set[str] = set()
    for node in nodes:
        meta = getattr(node, "metadata", None) or {}
        if not isinstance(meta, dict):
            continue
        sec = str(meta.get("biomed_section") or "").lower()
        if sec in _IMRAD_SECTIONS:
            sections.add(sec)
    if not sections:
        return 0.0
    return min(1.0, len(sections) / 3.0)


def _umls_density(sketch: str) -> float:
    if not sketch.strip():
        return 0.0
    hits = match_entities(sketch)
    unique = len({h.lower() for h in hits})
    if unique == 0:
        return 0.0
    return min(1.0, unique / max(1.0, math.sqrt(len(sketch))))


def _embed_text(text: str) -> list[float]:
    from eagle_rag.plugins.encoder_runtime import (
        deterministic_text_embedding,
        encode_text_for_encoder,
        l2_normalize,
    )

    try:
        return l2_normalize(encode_text_for_encoder("pubmedbert", text))
    except Exception:  # noqa: BLE001
        return l2_normalize(deterministic_text_embedding(text, _EMBED_DIM))


def _max_cosine(vec: list[float], prototypes: list[list[float]]) -> float:
    if not prototypes:
        return 0.0
    best = -1.0
    for proto in prototypes:
        score = sum(a * b for a, b in zip(vec, proto, strict=False))
        if score > best:
            best = score
    return max(0.0, best)


@lru_cache(maxsize=2)
def _load_prototype_vectors(config_path: str) -> dict[str, list[list[float]]]:
    path = Path(config_path)
    if not path.is_file():
        path = _DEFAULT_PROTOTYPE_PATH
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    protos = raw.get("prototypes") if isinstance(raw, dict) else {}
    out: dict[str, list[list[float]]] = {}
    if not isinstance(protos, dict):
        return out
    for label, texts in protos.items():
        if not isinstance(texts, list):
            continue
        vectors: list[list[float]] = []
        for item in texts:
            if isinstance(item, str) and item.strip():
                vectors.append(_embed_text(item))
        out[str(label)] = vectors
    return out


def _fusion_score(
    *,
    proto_margin: float,
    umls_density: float,
    imrad_diversity: float,
    sketch_entropy: float,
    cfg: dict[str, Any],
) -> float:
    fusion = cfg.get("fusion") if isinstance(cfg.get("fusion"), dict) else {}
    weights = fusion.get("weights") if isinstance(fusion.get("weights"), dict) else {}
    w_proto = float(weights.get("prototype", 0.55))
    w_umls = float(weights.get("umls", 0.25))
    w_imrad = float(weights.get("imrad", 0.15))
    w_entropy = float(weights.get("entropy", 0.05))
    return (
        w_proto * proto_margin
        + w_umls * umls_density
        + w_imrad * imrad_diversity
        + w_entropy * sketch_entropy
    )


def _llm_arbitrate(sketch: str, cfg: dict[str, Any]) -> DocumentTextProfile | None:
    llm_cfg = cfg.get("llm") if isinstance(cfg.get("llm"), dict) else {}
    if not bool(llm_cfg.get("enabled", True)):
        return None
    from eagle_rag.router.llm_factory import create_router_llm

    llm = create_router_llm(get_settings().llm)
    if llm is None:
        return None
    max_chars = int(llm_cfg.get("max_sketch_chars", 6000))
    prompt = (
        "Classify the document sketch as biomedical or general corporate text.\n"
        'Return JSON only: {"profile":"biomedical"|"general","confidence":0.0-1.0,'
        '"rationale":"..."}\n\n'
        f"Document sketch:\n{sketch[:max_chars]}"
    )
    try:
        response = llm.complete(prompt)
        text = str(getattr(response, "text", response) or "").strip()
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return None
        payload = json.loads(text[start : end + 1])
        profile_raw = str(payload.get("profile", "")).lower()
        if profile_raw not in {"biomedical", "general"}:
            return None
        confidence = float(payload.get("confidence", 0.7))
        return DocumentTextProfile(
            profile=profile_raw,  # type: ignore[arg-type]
            confidence=confidence,
            rule="llm_arbitrate",
            tier="tier2",
            signals={"llm_confidence": confidence},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("TDR LLM arbitrate skipped: %s", exc)
        return None


def classify_document_text_profile(nodes: list[Any]) -> DocumentTextProfile:
    """Run TDR Tier-0/1/2 and return a document-level text encoder profile."""
    cfg = _router_cfg()
    if not bool(cfg.get("enabled", True)):
        return DocumentTextProfile(
            profile="biomedical",
            confidence=0.5,
            rule="router_disabled_default",
            tier="tier0",
        )

    max_tokens = int(cfg.get("sketch_max_tokens", 2048))
    sketch = build_document_sketch(nodes, max_chars=max_tokens * 4)
    if not sketch.strip():
        ambiguous = str(cfg.get("ambiguous_default", "biomedical"))
        profile: TextProfile = "general" if ambiguous == "general" else "biomedical"
        return DocumentTextProfile(
            profile=profile,
            confidence=0.0,
            rule="empty_sketch_default",
            tier="tier1",
        )

    proto_path = str(cfg.get("prototype_config", _DEFAULT_PROTOTYPE_PATH))
    prototypes = _load_prototype_vectors(proto_path)
    vec = _embed_text(sketch)
    score_bio = _max_cosine(vec, prototypes.get("biomedical", []))
    score_gen = _max_cosine(vec, prototypes.get("general", []))
    proto_margin = score_bio - score_gen

    umls = _umls_density(sketch)
    imrad = _imrad_diversity(nodes)
    entropy = _sketch_entropy(sketch)
    confidence = _fusion_score(
        proto_margin=proto_margin,
        umls_density=umls,
        imrad_diversity=imrad,
        sketch_entropy=entropy,
        cfg=cfg,
    )

    threshold = float(cfg.get("confidence_threshold", 0.0))
    margin = float(cfg.get("llm_margin", 0.12))
    signals = {
        "proto_margin": proto_margin,
        "score_bio": score_bio,
        "score_gen": score_gen,
        "umls_density": umls,
        "imrad_diversity": imrad,
        "sketch_entropy": entropy,
        "fusion_confidence": confidence,
    }

    if confidence > threshold + margin:
        return DocumentTextProfile(
            profile="biomedical",
            confidence=confidence,
            rule="tier1_fusion_biomedical",
            tier="tier1",
            signals=signals,
        )
    if confidence < threshold - margin:
        return DocumentTextProfile(
            profile="general",
            confidence=confidence,
            rule="tier1_fusion_general",
            tier="tier1",
            signals=signals,
        )

    llm_result = _llm_arbitrate(sketch, cfg)
    if llm_result is not None:
        merged = dict(signals)
        merged.update(llm_result.signals)
        return DocumentTextProfile(
            profile=llm_result.profile,
            confidence=llm_result.confidence,
            rule=llm_result.rule,
            tier="tier2",
            signals=merged,
        )

    ambiguous = str(cfg.get("ambiguous_default", "biomedical"))
    profile = "general" if ambiguous == "general" else "biomedical"
    return DocumentTextProfile(
        profile=profile,
        confidence=confidence,
        rule="ambiguous_default",
        tier="tier1",
        signals=signals,
    )


def apply_text_profile_to_nodes(
    nodes: list[Any],
    profile: DocumentTextProfile,
) -> None:
    """Stamp TDR decision on every node metadata dict."""
    for node in nodes:
        meta = getattr(node, "metadata", None)
        if not isinstance(meta, dict):
            continue
        meta["biomed_text_profile"] = profile.profile
        meta["biomed_text_profile_rule"] = profile.rule
        meta["biomed_text_profile_confidence"] = profile.confidence
        meta["biomed_text_profile_tier"] = profile.tier
