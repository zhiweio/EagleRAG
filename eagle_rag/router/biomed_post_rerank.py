"""Post-RRF biomed rerank: domain cosine + document-name drug boosting."""

from __future__ import annotations

from llama_index.core.schema import ImageNode, NodeWithScore

__all__ = ["biomed_post_rrf_rerank"]


def _node_text(nws: NodeWithScore) -> str:
    node = nws.node
    if hasattr(node, "get_content"):
        text = node.get_content() or ""
        if text:
            return str(text)
    return str(getattr(node, "text", "") or "")


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


def _enrich_file_names(nodes: list[NodeWithScore], *, plugin_namespace: str) -> None:
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


def _cosine_rerank(
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
    out: list[NodeWithScore] = []
    for score, nws in scored:
        out.append(NodeWithScore(node=nws.node, score=score))
    return out


def _filename_drug_boost(
    nodes: list[NodeWithScore],
    boost_terms: list[str],
) -> list[NodeWithScore]:
    if not boost_terms:
        return nodes
    boosted: list[NodeWithScore] = []
    for nws in nodes:
        meta = nws.node.metadata or {}
        fname = str(meta.get("file_name") or meta.get("document_name") or "").lower()
        text_l = _node_text(nws).lower()
        bonus = 0.0
        for term in boost_terms:
            if term in fname:
                # Strong boost for compound/label/company docs matching the drug name.
                if any(prefix in fname for prefix in ("compound_", "label_", "company_")):
                    bonus = max(bonus, 3.0)
                else:
                    bonus = max(bonus, 1.5)
            elif term in text_l and "compound_" in fname:
                bonus = max(bonus, 1.0)
        score = (nws.score or 0.0) + bonus
        boosted.append(NodeWithScore(node=nws.node, score=score))
    boosted.sort(key=lambda item: item.score or 0.0, reverse=True)
    return boosted


def biomed_post_rrf_rerank(
    nodes: list[NodeWithScore],
    query: str,
    *,
    top_n: int,
    plugin_namespace: str = "biomed",
) -> list[NodeWithScore]:
    """Re-score fused biomed hits after RRF (restores domain ranking + filename boost)."""
    text_nodes = [n for n in nodes if not isinstance(n.node, ImageNode)]
    image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
    if not text_nodes:
        return nodes[:top_n]

    _enrich_file_names(text_nodes, plugin_namespace=plugin_namespace)
    boost_terms = _boost_terms_for_query(query)

    reranked = _cosine_rerank(text_nodes, query, encoder="pubmedbert")

    compound_cue = any(
        token in query.lower() for token in ("smiles", "inchi", "compound", "ligand", "mol")
    )
    if compound_cue:
        compound_candidates = [
            n
            for n in reranked
            if "compound_" in str((n.node.metadata or {}).get("file_name") or "").lower()
        ]
        if compound_candidates:
            mol_ranked = _cosine_rerank(compound_candidates, query, encoder="molformer")
            mol_by_id = {n.node.node_id: n for n in mol_ranked if n.node.node_id}
            merged: list[NodeWithScore] = []
            for nws in reranked:
                node_id = nws.node.node_id
                mol = mol_by_id.get(node_id) if node_id else None
                if mol and (mol.score or 0.0) > (nws.score or 0.0):
                    merged.append(mol)
                else:
                    merged.append(nws)
            reranked = merged

    reranked = _filename_drug_boost(reranked, boost_terms)
    reranked.sort(key=lambda item: item.score or 0.0, reverse=True)
    return reranked[:top_n] + image_nodes
