"""Visual retriever merge tests."""

from __future__ import annotations

from eagle_rag.retrievers.pixelrag_visual_retriever import merge_visual_hits


def test_merge_visual_hits_keeps_max_score():
    a = [{"image_id": "img-1", "score": 0.4}]
    b = [{"image_id": "img-1", "score": 0.9}, {"image_id": "img-2", "score": 0.5}]
    merged = merge_visual_hits(a, b, top_k=2)
    assert len(merged) == 2
    by_id = {row["image_id"]: row["score"] for row in merged}
    assert by_id["img-1"] == 0.9
    assert by_id["img-2"] == 0.5
