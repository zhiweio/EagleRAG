#!/usr/bin/env python3
"""Retrieval eval smoke against live biomed API (Hit@K / Recall@K / MRR / term coverage)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
DATASETS = ROOT / "eval" / "biomed" / "datasets"
RESULTS = ROOT / "eval" / "biomed" / "results"

sys.path.insert(0, str(SCRIPTS))
from corpus_index import resolve_search_mode  # noqa: E402
from metrics import (  # noqa: E402
    mean,
    non_llm_context_recall,
    substring_hit,
    term_coverage,
)


def _req(url: str, payload: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
    data = json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "eagle-rag-biomed-eval/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _load_queries(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _chunk_evidence(ch: dict[str, Any]) -> str:
    """Single ranked evidence blob: filename + path + body (for substring / term metrics)."""
    parts = [
        ch.get("file_name"),
        ch.get("document_name"),
        ch.get("name"),
        ch.get("path"),
        ch.get("document_id"),
        ch.get("content"),
        ch.get("text"),
        ch.get("content_summary"),
    ]
    return " ".join(str(p) for p in parts if p)


def _extract_chunks(search: dict[str, Any]) -> list[str]:
    """Return ranked per-chunk evidence strings from SearchResponse."""
    blobs: list[str] = []
    sources = search.get("sources") or {}
    chunks: list[Any] = []
    if isinstance(sources, dict):
        chunks = list(sources.get("text") or []) + list(sources.get("visual") or [])
    elif isinstance(sources, list):
        chunks = sources
    for ch in chunks:
        if isinstance(ch, dict):
            blobs.append(_chunk_evidence(ch))
    return blobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument(
        "--queries",
        default=str(DATASETS / "eval_queries.smoke.jsonl"),
        help="JSONL gold set (smoke or full)",
    )
    ap.add_argument("--hit-threshold", type=float, default=None)
    ap.add_argument("--recall-threshold", type=float, default=None)
    ap.add_argument("--mrr-threshold", type=float, default=None)
    ap.add_argument("--term-threshold", type=float, default=None)
    ap.add_argument("--fail-under-threshold", action="store_true", default=True)
    ap.add_argument("--no-fail", action="store_true", help="Always exit 0; still write report")
    ap.add_argument(
        "--respect-route-hint",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use hybrid search when route_hint requests eagle_chemical (default: true)",
    )
    args = ap.parse_args()

    # Deterministic/hash encoders (offline CI) cannot meet native-embedding gates.
    offline = os.environ.get("EAGLE_BIOMED_ENCODER_MODE", "").strip().lower() == "deterministic"
    if args.hit_threshold is None:
        args.hit_threshold = 0.20 if offline else 0.70
    if args.recall_threshold is None:
        args.recall_threshold = 0.15 if offline else 0.50
    if args.mrr_threshold is None:
        args.mrr_threshold = 0.15 if offline else 0.55
    if args.term_threshold is None:
        args.term_threshold = 0.50 if offline else 0.80
    if offline:
        print(
            "encoder_mode=deterministic: using offline smoke thresholds "
            f"(hit>={args.hit_threshold}, recall>={args.recall_threshold}, "
            f"mrr>={args.mrr_threshold}, term>={args.term_threshold})"
        )

    qpath = Path(args.queries)
    if not qpath.exists():
        print(f"missing queries file: {qpath}; run generate_eval_queries.py")
        return 1
    queries = _load_queries(qpath)
    base = args.base_url.rstrip("/")

    hit_scores: list[float] = []
    recall_scores: list[float] = []
    mrr_scores: list[float] = []
    term_scores: list[float] = []
    ctx_scores: list[float] = []
    details: list[dict[str, Any]] = []

    for row in queries:
        q = row["query"]
        k = int(row.get("k") or 5)
        needles = list(row.get("expected_doc_name_substrings") or [])
        terms = list(row.get("must_include_terms") or [])
        mode = resolve_search_mode(row, respect_route_hint=args.respect_route_hint)
        try:
            search = _req(
                f"{base}/search",
                {"query": q, "kb_name": args.kb_name, "mode": mode},
            )
        except Exception as exc:  # noqa: BLE001
            print("search failed", row.get("id"), exc)
            hit_scores.append(0.0)
            recall_scores.append(0.0)
            mrr_scores.append(0.0)
            term_scores.append(0.0)
            details.append({"id": row.get("id"), "error": str(exc)})
            continue

        chunks = _extract_chunks(search)
        top_chunks = chunks[:k]
        # Hit@K: any expected doc-name substring appears in a top-k chunk blob.
        h = (
            substring_hit(needles, top_chunks, k)
            if needles
            else substring_hit(terms, top_chunks, k)
        )
        # Recall@K: fraction of expected substrings found across top-k chunk blobs.
        if needles:
            top_blob = " ".join(top_chunks).lower()
            r = sum(1 for n in needles if n.lower() in top_blob) / len(needles)
        else:
            r = h
        # MRR over first matching chunk rank.
        rr = 0.0
        targets = [n.lower() for n in (needles or terms)]
        for i, blob in enumerate(top_chunks, start=1):
            low = blob.lower()
            if any(t in low for t in targets if t):
                rr = 1.0 / i
                break
        tc = term_coverage(terms, top_chunks)
        ctx = non_llm_context_recall(top_chunks, [q] + terms)

        hit_scores.append(h)
        recall_scores.append(r)
        mrr_scores.append(rr)
        term_scores.append(tc)
        if ctx is not None:
            ctx_scores.append(ctx)
        details.append(
            {
                "id": row.get("id"),
                "workflow": row.get("workflow"),
                "query": q,
                "search_mode": mode,
                "hit": h,
                "recall": r,
                "mrr": rr,
                "term_coverage": tc,
                "context_recall": ctx,
                "n_sources": len(chunks),
            }
        )
        time.sleep(0.05)

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "kb_name": args.kb_name,
        "queries_file": str(qpath),
        "n_queries": len(queries),
        "metrics": {
            "hit_at_k": mean(hit_scores),
            "recall_at_k": mean(recall_scores),
            "mrr": mean(mrr_scores),
            "term_coverage": mean(term_scores),
            "non_llm_context_recall": mean(ctx_scores) if ctx_scores else None,
        },
        "thresholds": {
            "hit_at_k": args.hit_threshold,
            "recall_at_k": args.recall_threshold,
            "mrr": args.mrr_threshold,
            "term_coverage": args.term_threshold,
        },
        "details": details,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"smoke_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    m = report["metrics"]
    print(json.dumps(m, indent=2))
    print("wrote", out)

    if args.no_fail:
        return 0
    ok = (
        m["hit_at_k"] >= args.hit_threshold
        and m["recall_at_k"] >= args.recall_threshold
        and m["mrr"] >= args.mrr_threshold
        and m["term_coverage"] >= args.term_threshold
    )
    if not ok:
        print("FAIL under threshold")
        return 2
    print("EVAL SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
