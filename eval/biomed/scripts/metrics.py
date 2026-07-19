"""Retrieval metrics for biomed eval smoke (Hit@K, Recall@K, MRR, term coverage)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def hit_at_k(relevant: Sequence[str], ranked: Sequence[str], k: int) -> float:
    """1.0 if any relevant id appears in top-k ranked ids."""
    if not relevant:
        return 0.0
    top = {_norm(x) for x in ranked[:k]}
    return 1.0 if any(_norm(r) in top for r in relevant) else 0.0


def recall_at_k(relevant: Sequence[str], ranked: Sequence[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = {_norm(x) for x in ranked[:k]}
    hits = sum(1 for r in relevant if _norm(r) in top)
    return hits / len(relevant)


def mrr(relevant: Sequence[str], ranked: Sequence[str]) -> float:
    if not relevant:
        return 0.0
    rel = {_norm(r) for r in relevant}
    for i, doc_id in enumerate(ranked, start=1):
        if _norm(doc_id) in rel:
            return 1.0 / i
    return 0.0


def term_coverage(terms: Sequence[str], texts: Iterable[str]) -> float:
    if not terms:
        return 1.0
    blob = _norm(" ".join(texts))
    hits = sum(1 for t in terms if _norm(t) in blob)
    return hits / len(terms)


def substring_hit(needles: Sequence[str], haystacks: Sequence[str], k: int) -> float:
    """1.0 if any needle is a substring of any of the top-k haystack strings."""
    if not needles:
        return 0.0
    top = [_norm(h) for h in haystacks[:k]]
    for n in needles:
        nn = _norm(n)
        if nn and any(nn in h for h in top):
            return 1.0
    return 0.0


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def non_llm_context_recall(
    retrieved_contexts: Sequence[str],
    reference_contexts: Sequence[str],
) -> float | None:
    """Optional Ragas NonLLMContextRecall; returns None if ragas unavailable."""
    if not reference_contexts:
        return None
    try:
        from ragas.dataset_schema import SingleTurnSample
        from ragas.metrics import NonLLMContextRecall
    except Exception:  # noqa: BLE001
        # Fallback: fraction of reference snippets whose tokens appear in retrieved text.
        blob = _norm(" ".join(retrieved_contexts))
        hits = 0
        for ref in reference_contexts:
            tokens = [t for t in _norm(ref).split() if len(t) > 3]
            if not tokens:
                continue
            if sum(1 for t in tokens if t in blob) / len(tokens) >= 0.5:
                hits += 1
        return hits / len(reference_contexts)

    sample = SingleTurnSample(
        retrieved_contexts=list(retrieved_contexts),
        reference_contexts=list(reference_contexts),
    )
    metric = NonLLMContextRecall()
    import asyncio

    async def _score() -> float:
        return float(await metric.single_turn_ascore(sample))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_score())
    # Already inside an event loop — use token overlap fallback
    blob = _norm(" ".join(retrieved_contexts))
    hits = 0
    for ref in reference_contexts:
        tokens = [t for t in _norm(ref).split() if len(t) > 3]
        if tokens and sum(1 for t in tokens if t in blob) / len(tokens) >= 0.5:
            hits += 1
    return hits / len(reference_contexts)
