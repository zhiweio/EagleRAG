"""Biomed domain rerank: MedCPT cross-encoder + metadata signal fusion."""

from __future__ import annotations

from typing import Any

from llama_index.core.schema import ImageNode, NodeWithScore

from eagle_rag.config import get_settings, plugin_options
from eagle_rag.plugins.routing import QueryRetrievalIntent

__all__ = [
    "cosine_rerank",
    "enrich_file_names",
    "post_rrf_rerank",
    "score_retrieval_signals",
]


def _node_text(nws: NodeWithScore) -> str:
    node = nws.node
    if hasattr(node, "get_content"):
        text = node.get_content() or ""
        if text:
            return str(text)
    return str(getattr(node, "text", "") or "")


def _scoring_weights() -> dict[str, float]:
    try:
        opts = plugin_options("biomed", get_settings())
        raw = opts.get("retrieval_scoring") or {}
        if isinstance(raw, dict):
            return {
                "w_ce": float(raw.get("w_ce", 0.7)),
                "w_sec": float(raw.get("w_sec", 0.2)),
                "w_fname": float(raw.get("w_fname", 0.1)),
                "w_compound_penalty": float(raw.get("w_compound_penalty", 1.5)),
                "w_xdrug_penalty": float(raw.get("w_xdrug_penalty", 2.0)),
            }
    except Exception:  # noqa: BLE001
        pass
    return {
        "w_ce": 0.7,
        "w_sec": 0.2,
        "w_fname": 0.1,
        "w_compound_penalty": 1.5,
        "w_xdrug_penalty": 2.0,
    }


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


def _filename_boost(meta: dict[str, Any], boost_terms: list[str]) -> float:
    if not boost_terms:
        return 0.0
    fname = str(meta.get("file_name") or meta.get("document_name") or "").lower()
    bonus = 0.0
    for term in boost_terms:
        if term in fname:
            if any(prefix in fname for prefix in ("compound_", "label_", "company_")):
                bonus = max(bonus, 1.0)
            else:
                bonus = max(bonus, 0.5)
    return bonus


def _compound_penalty(meta: dict[str, Any], intent: QueryRetrievalIntent | None) -> float:
    if intent is None or "eagle_chemical" not in intent.suppress_collections:
        return 0.0
    fname = str(meta.get("file_name") or meta.get("document_name") or "").lower()
    doc_type = str(meta.get("biomed_doc_type") or "").lower()
    if "compound_" in fname or doc_type == "compound":
        return 1.0
    return 0.0


def _cross_drug_penalty(meta: dict[str, Any], query_drugs: list[str]) -> float:
    if not query_drugs:
        return 0.0
    query_set = {d.lower() for d in query_drugs}
    raw_drugs = meta.get("primary_drugs")
    doc_drugs: list[str] = []
    if isinstance(raw_drugs, list):
        doc_drugs = [str(d).lower() for d in raw_drugs if d]
    elif isinstance(raw_drugs, str) and raw_drugs.strip():
        doc_drugs = [raw_drugs.lower()]
    if doc_drugs and not (query_set & set(doc_drugs)):
        return 1.0
    fname = str(meta.get("file_name") or meta.get("document_name") or "").lower()
    if doc_drugs:
        return 0.0
    if query_set and not any(drug in fname for drug in query_set):
        text_l = str(meta.get("path") or "").lower()
        if not any(drug in text_l for drug in query_set):
            return 0.5
    return 0.0


def score_retrieval_signals(
    nws: NodeWithScore,
    query: str,
    intent: QueryRetrievalIntent | None,
    *,
    boost_terms: list[str] | None = None,
) -> float:
    weights = _scoring_weights()
    meta = nws.node.metadata or {}
    terms = boost_terms if boost_terms is not None else _boost_terms_for_query(query)
    section_cues = intent.section_cues if intent else ()
    query_drugs = terms

    sec = _section_match_score(meta, section_cues)
    fname = _filename_boost(meta, terms)
    compound = _compound_penalty(meta, intent)
    xdrug = _cross_drug_penalty(meta, query_drugs)

    return (
        weights["w_sec"] * sec
        + weights["w_fname"] * fname
        - weights["w_compound_penalty"] * compound
        - weights["w_xdrug_penalty"] * xdrug
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
    """Re-score fused biomed hits after RRF with MedCPT CE + metadata signals."""
    text_nodes = [n for n in nodes if not isinstance(n.node, ImageNode)]
    image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
    if not text_nodes:
        return nodes[:top_n]

    if intent is None:
        from plugins.biomed.query_intent import detect_retrieval_intent

        intent = detect_retrieval_intent(query)

    enrich_file_names(text_nodes, plugin_namespace=plugin_namespace)
    boost_terms = _boost_terms_for_query(query)
    weights = _scoring_weights()

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

    compound_cue = any(
        token in query.lower() for token in ("smiles", "inchi", "compound", "ligand", "mol")
    )
    if compound_cue:
        compound_candidates = [
            n
            for n in scored
            if "compound_" in str((n[1].node.metadata or {}).get("file_name") or "").lower()
        ]
        if compound_candidates:
            mol_ranked = cosine_rerank(
                [nws for _, nws in compound_candidates],
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
