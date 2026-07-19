"""Biomed domain rerank: MedCPT cross-encoder + entity/content-form signal fusion."""

from __future__ import annotations

import json
from typing import Any

from llama_index.core.schema import ImageNode, NodeWithScore

from eagle_rag.config import get_settings, plugin_options
from eagle_rag.plugins.routing import QueryRetrievalIntent
from plugins.biomed.scoring import entity_boost_score

__all__ = [
    "cosine_rerank",
    "enrich_file_names",
    "post_rrf_rerank",
    "score_retrieval_signals",
]

_DEFAULT_WEIGHTS: dict[str, float] = {
    "w_ce": 0.50,
    "w_entity": 0.25,
    "w_sec": 0.15,
    "w_xdrug_penalty": 2.0,
}

_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "regulatory": {
        "w_ce": 0.30,
        "w_entity": 0.20,
        "w_sec": 0.35,
        "w_xdrug_penalty": 2.5,
    },
    "drug_entity": {
        "w_ce": 0.35,
        "w_entity": 0.35,
        "w_sec": 0.10,
        "w_xdrug_penalty": 3.0,
    },
    "chemical": {
        "w_ce": 0.25,
        "w_entity": 0.40,
        "w_sec": 0.10,
        "w_xdrug_penalty": 3.0,
    },
    "combination": {
        "w_ce": 0.35,
        "w_entity": 0.35,
        "w_sec": 0.10,
        "w_xdrug_penalty": 2.5,
    },
}


def _node_text(nws: NodeWithScore) -> str:
    node = nws.node
    if hasattr(node, "get_content"):
        text = node.get_content() or ""
        if text:
            return str(text)
    return str(getattr(node, "text", "") or "")


def _scoring_weights(intent: QueryRetrievalIntent | None) -> dict[str, float]:
    profile = (intent.workflow if intent else "general") or "general"
    weights = dict(_DEFAULT_WEIGHTS)
    if profile in _PROFILE_WEIGHTS:
        weights.update(_PROFILE_WEIGHTS[profile])
    try:
        opts = plugin_options("biomed", get_settings())
        raw = opts.get("retrieval_scoring") or {}
        if isinstance(raw, dict):
            profile_raw = raw.get(profile) if isinstance(raw.get(profile), dict) else raw
            if isinstance(profile_raw, dict):
                for key in ("w_ce", "w_entity", "w_sec", "w_xdrug_penalty"):
                    if key in profile_raw:
                        weights[key] = float(profile_raw[key])
    except Exception:  # noqa: BLE001
        pass
    return weights


def _domain_rerank_encoder_name() -> str:
    try:
        opts = plugin_options("biomed", get_settings())
        return str(opts.get("domain_rerank_encoder") or "medcpt-rerank")
    except Exception:  # noqa: BLE001
        return "medcpt-rerank"


def _boost_terms_for_query(query: str) -> list[str]:
    from plugins.biomed.umls import match_drug_entities, match_entities, resolve_entity

    explicit_drugs = [d.lower() for d in match_drug_entities(query)]
    if explicit_drugs:
        return list(dict.fromkeys(explicit_drugs))

    terms: list[str] = []
    for entity in match_entities(query):
        resolved = resolve_entity(entity)
        if resolved.get("found"):
            terms.extend(str(d).lower() for d in (resolved.get("related_drugs") or [])[:6])
    return list(dict.fromkeys(terms))


def enrich_file_names(nodes: list[NodeWithScore], *, plugin_namespace: str) -> None:
    from eagle_rag.index.registry import lookup_documents_sync

    doc_ids = [
        str((nws.node.metadata or {}).get("document_id") or "")
        for nws in nodes
        if (nws.node.metadata or {}).get("document_id")
    ]
    if not doc_ids:
        return
    docs = lookup_documents_sync(doc_ids, plugin_namespace=plugin_namespace)
    for nws in nodes:
        meta = dict(nws.node.metadata or {})
        doc_id = str(meta.get("document_id") or "")
        doc = docs.get(doc_id)
        if not doc:
            continue
        name = doc.get("name")
        if name:
            meta["file_name"] = name
            meta["document_name"] = name
        nws.node.metadata = meta


def cosine_rerank(
    nodes: list[NodeWithScore],
    query: str,
    *,
    encoder: str,
) -> list[NodeWithScore]:
    if not nodes:
        return nodes
    try:
        from eagle_rag.plugins.encoder_runtime import encode_text_for_encoder
    except Exception:  # noqa: BLE001
        return nodes
    try:
        q_vec = encode_text_for_encoder(encoder, query)
    except Exception:  # noqa: BLE001
        return nodes

    scored: list[tuple[float, NodeWithScore]] = []
    for nws in nodes:
        text = _node_text(nws)[:2048]
        try:
            d_vec = encode_text_for_encoder(encoder, text)
            score = sum(a * b for a, b in zip(q_vec, d_vec, strict=False))
        except Exception:  # noqa: BLE001
            score = float(nws.score or 0.0)
        scored.append((float(score), nws))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [NodeWithScore(node=nws.node, score=score) for score, nws in scored]


def _section_match_score(meta: dict[str, Any], section_cues: tuple[str, ...]) -> float:
    if not section_cues:
        return 0.0
    section = str(meta.get("biomed_section") or "").lower()
    path = str(meta.get("path") or "").lower()
    text_head = str(meta.get("content_summary") or "")[:200].lower()
    blob = f"{section} {path} {text_head}"
    hits = sum(
        1 for cue in section_cues if cue.lower() in blob or cue.lower().replace("_", " ") in blob
    )
    return hits / len(section_cues)


def _entity_match_score(
    meta: dict[str, Any],
    text: str,
    query_drugs: list[str],
) -> float:
    if not query_drugs:
        return 0.0
    boost = entity_boost_score(meta, query_drugs)
    if boost >= 1.0:
        return 1.0
    if boost >= 0.5:
        return 0.75
    text_l = text[:512].lower()
    query_set = {d.lower() for d in query_drugs if d}
    if any(drug in text_l for drug in query_set):
        return 0.75
    return 0.0


def _cross_drug_penalty(
    meta: dict[str, Any],
    query_drugs: list[str],
    *,
    text: str,
) -> float:
    if not query_drugs:
        return 0.0
    query_set = {d.lower() for d in query_drugs}
    raw_drugs = meta.get("primary_drugs")
    doc_drugs: list[str] = []
    if isinstance(raw_drugs, list):
        doc_drugs = [str(d).lower() for d in raw_drugs if d]
    elif isinstance(raw_drugs, str) and raw_drugs.strip():
        text_raw = raw_drugs.strip()
        if text_raw.startswith("["):
            try:
                parsed = json.loads(text_raw)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                doc_drugs = [str(d).lower() for d in parsed if d]
        else:
            doc_drugs = [text_raw.lower()]

    blob = f"{text[:512]} {meta.get('path') or ''}".lower()
    if any(drug in blob for drug in query_set):
        return 0.0
    if doc_drugs and not (query_set & set(doc_drugs)):
        return 1.0
    if doc_drugs:
        return 0.0
    return 1.0


def score_retrieval_signals(
    nws: NodeWithScore,
    query: str,
    intent: QueryRetrievalIntent | None,
    *,
    boost_terms: list[str] | None = None,
) -> float:
    weights = _scoring_weights(intent)
    meta = nws.node.metadata or {}
    text = _node_text(nws)
    terms = boost_terms if boost_terms is not None else _boost_terms_for_query(query)
    section_cues = intent.section_cues if intent else ()

    entity = _entity_match_score(meta, text, terms)
    sec = _section_match_score(meta, section_cues)
    xdrug = _cross_drug_penalty(meta, terms, text=text)

    return (
        weights["w_entity"] * entity + weights["w_sec"] * sec - weights["w_xdrug_penalty"] * xdrug
    )


def _medcpt_scores(query: str, nodes: list[NodeWithScore]) -> list[float]:
    if not nodes:
        return []
    texts = [_node_text(nws)[:2048] for nws in nodes]
    try:
        from eagle_rag.plugins.encoder_runtime import score_rerank_for_encoder

        encoder_name = _domain_rerank_encoder_name()
        return score_rerank_for_encoder(encoder_name, query, texts)
    except Exception:  # noqa: BLE001
        return [float(nws.score or 0.0) for nws in nodes]


def post_rrf_rerank(
    nodes: list[NodeWithScore],
    query: str,
    *,
    top_n: int,
    plugin_namespace: str = "biomed",
    intent: QueryRetrievalIntent | None = None,
) -> list[NodeWithScore]:
    """Re-score fused biomed hits after RRF with MedCPT CE + entity/content signals."""
    text_nodes = [n for n in nodes if not isinstance(n.node, ImageNode)]
    image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
    if not text_nodes:
        return nodes[:top_n]

    if intent is None:
        from plugins.biomed.query_intent import detect_retrieval_intent

        intent = detect_retrieval_intent(query)

    enrich_file_names(text_nodes, plugin_namespace=plugin_namespace)
    boost_terms = _boost_terms_for_query(query)
    weights = _scoring_weights(intent)

    ce_scores = _medcpt_scores(query, text_nodes)
    if len(ce_scores) != len(text_nodes):
        ce_scores = [float(nws.score or 0.0) for nws in text_nodes]

    ce_min = min(ce_scores)
    ce_max = max(ce_scores)
    ce_span = ce_max - ce_min or 1.0

    scored: list[tuple[float, NodeWithScore]] = []
    for nws, ce_raw in zip(text_nodes, ce_scores, strict=False):
        ce_norm = (ce_raw - ce_min) / ce_span
        signals = score_retrieval_signals(nws, query, intent, boost_terms=boost_terms)
        final = weights["w_ce"] * ce_norm + signals
        scored.append((final, NodeWithScore(node=nws.node, score=final)))

    if intent.workflow == "chemical":
        chemical_nodes = [
            n
            for n in scored
            if _entity_match_score(n[1].node.metadata or {}, _node_text(n[1]), boost_terms) > 0
        ]
        if chemical_nodes:
            mol_ranked = cosine_rerank(
                [nws for _, nws in chemical_nodes],
                query,
                encoder="molformer",
            )
            mol_by_id = {n.node.node_id: n for n in mol_ranked if n.node.node_id}
            merged: list[tuple[float, NodeWithScore]] = []
            for score, nws in scored:
                node_id = nws.node.node_id
                mol = mol_by_id.get(node_id) if node_id else None
                if mol and (mol.score or 0.0) > (nws.score or 0.0):
                    merged.append((float(mol.score or score), mol))
                else:
                    merged.append((score, nws))
            scored = merged

    scored.sort(key=lambda item: item[0], reverse=True)
    return [nws for _, nws in scored[:top_n]] + image_nodes
