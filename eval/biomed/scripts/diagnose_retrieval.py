#!/usr/bin/env python3
"""Diagnose retrieval failures for biomed eval queries (corpus / route / ranking)."""

from __future__ import annotations

import argparse
import json
import sys
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
sys.path.insert(0, str(ROOT))

from corpus_index import (  # noqa: E402
    match_corpus_files,
    resolve_search_mode,
    scan_corpus,
    terms_in_text,
)
from metrics import substring_hit, term_coverage  # noqa: E402

DEFAULT_FAILED_IDS = [
    "q-seed-008",
    "q-seed-010",
    "q-seed-011",
    "q-seed-014",
    "q-seed-016",
    "q-seed-018",
    "q-exp-024",
    "q-exp-030",
]


def _get(url: str, timeout: float = 60.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "eagle-rag-biomed-diag/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, payload: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "eagle-rag-biomed-diag/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _load_queries(path: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        out[str(row["id"])] = row
    return out


def _fetch_kb_documents(base: str, kb_name: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    offset = 0
    limit = 500
    while True:
        data = _get(f"{base}/documents?kb_name={kb_name}&limit={limit}&offset={offset}")
        batch = data.get("items") or []
        items.extend(batch)
        total = int(data.get("total") or len(items))
        offset += limit
        if offset >= total or not batch:
            break
    return items


def _route_plan(query: str, route_mode: str = "text") -> list[dict[str, str]]:
    try:
        from plugins.biomed.query_route import BiomedQueryRouteClassifier

        clf = BiomedQueryRouteClassifier()
        decision = clf.route(query, "biomed", route_mode=route_mode)
        if decision is None:
            return []
        return [{"collection": p.collection, "encoder": p.encoder} for p in decision.plans]
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)}]


def _extract_hits(search: dict[str, Any], k: int = 5) -> list[dict[str, Any]]:
    sources = search.get("sources") or {}
    chunks: list[Any] = []
    if isinstance(sources, dict):
        chunks = list(sources.get("text") or []) + list(sources.get("visual") or [])
    rows: list[dict[str, Any]] = []
    for ch in chunks[:k]:
        if not isinstance(ch, dict):
            continue
        content = str(ch.get("content") or ch.get("text") or "")
        rows.append(
            {
                "file_name": ch.get("file_name") or ch.get("document_name"),
                "document_id": ch.get("document_id"),
                "path": ch.get("path"),
                "score": ch.get("score"),
                "content_preview": content[:200],
            }
        )
    return rows


def _parse_api_steps(steps: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"stages": []}
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or "")
        if name == "route":
            out["route"] = {
                k: step.get(k)
                for k in ("mode", "collections", "plans", "reason")
                if step.get(k) is not None
            }
            out["stages"].append("route")
        elif name == "recall":
            out["recall"] = {
                "text_count": step.get("text_count"),
                "visual_count": step.get("visual_count"),
                "recall_top_k": step.get("recall_top_k"),
            }
            out["stages"].append("recall")
        elif name == "rerank":
            out["merged_rerank"] = {
                "model": step.get("model"),
                "text_count": step.get("text_count"),
            }
            out["stages"].append("merged_rerank")
    return out


def _local_pipeline_preview(query: str) -> dict[str, Any]:
    """Offline stage checklist: intent, expand, rerank policy (no Milvus)."""
    from eagle_rag.plugins.hookbus import HookContext
    from eagle_rag.plugins.rerank_policy import rerank_model_label, resolve_rerank_policy
    from plugins.biomed.query_intent import detect_retrieval_intent
    from plugins.biomed.retrieval_hooks import biomed_dense_expand

    intent = detect_retrieval_intent(query)
    ctx = HookContext(plugin_namespace="biomed")
    expanded = biomed_dense_expand(ctx, query, encoder="pubmedbert")
    policy = resolve_rerank_policy("biomed")
    rerank_model = rerank_model_label("biomed")

    stage_pipeline = [
        "QUERY_DENSE_EXPAND",
        "ANN (per CollectionQueryPlan)",
        "RERANK (Tier-1 cosine)",
        "RETRIEVE_SUPPLEMENT",
        "RRF merge",
        "RERANK_MERGED (domain) or qwen3-rerank (core)",
    ]
    return {
        "stage_pipeline": stage_pipeline,
        "retrieval_intent": {
            "workflow": intent.workflow,
            "prefer_doc_types": list(intent.prefer_doc_types or ()),
            "suppress_collections": list(intent.suppress_collections or ()),
            "section_cues": list(intent.section_cues or ()),
        },
        "dense_expand": {
            "dense_query": expanded.dense_query if expanded else query,
            "sparse_terms": list(expanded.sparse_terms) if expanded else [],
        },
        "rerank_policy": str(policy),
        "merged_rerank_model": rerank_model,
    }


def _classify_failure(
    row: dict[str, Any],
    corpus_hits: list[Any],
    kb_hits: list[dict[str, Any]],
    text_hits: list[dict[str, Any]],
    hybrid_hits: list[dict[str, Any]],
    route_text: list[dict[str, str]],
    route_hybrid: list[dict[str, str]],
) -> str:
    expected = list(row.get("expected_doc_name_substrings") or [])
    terms = list(row.get("must_include_terms") or [])
    k = int(row.get("k") or 5)

    def blobs(hits: list[dict[str, Any]]) -> list[str]:
        return [
            " ".join(str(h.get(x) or "") for x in ("file_name", "document_id", "content_preview"))
            for h in hits
        ]

    text_blobs = blobs(text_hits)
    hit_text = substring_hit(expected or terms, text_blobs, k) if (expected or terms) else 0.0
    tc_text = term_coverage(terms, text_blobs) if terms else 1.0

    # Corpus gaps
    if expected and not corpus_hits:
        return "gold_corpus_gap"
    for sub in expected:
        if not any(sub.lower() in cf.name.lower() for cf in corpus_hits):
            return "gold_corpus_gap"
    if len(expected) > 1:
        missing = [
            s for s in expected if not any(s.lower() in cf.name.lower() for cf in corpus_hits)
        ]
        if missing:
            return "gold_over_specified"

    # Route gap: gold only in chemical collection paths
    gold_collections = {
        c for doc in kb_hits for c in (doc.get("extra") or {}).get("collections_used") or []
    }
    if "eagle_chemical" in gold_collections and hit_text < 1.0:
        hybrid_blobs = blobs(hybrid_hits)
        if substring_hit(expected or terms, hybrid_blobs, k):
            return "query_route_gap"

    if hit_text >= 1.0 and tc_text < 1.0:
        return "term_metric_strict"

    if kb_hits and hit_text < 1.0:
        return "ranking_gap"

    if hit_text < 1.0:
        return "gold_corpus_gap"

    return "ok"


def diagnose_row(
    row: dict[str, Any],
    *,
    base: str,
    kb_name: str,
    corpus_files: list[Any],
    kb_docs: list[dict[str, Any]],
) -> dict[str, Any]:
    query = str(row["query"])
    expected = list(row.get("expected_doc_name_substrings") or [])
    terms = list(row.get("must_include_terms") or [])

    corpus_hits = match_corpus_files(corpus_files, expected)
    corpus_detail = []
    for cf in corpus_hits:
        head = cf.read_head()
        ok, missing = terms_in_text(terms, head) if terms else (True, [])
        corpus_detail.append(
            {
                "file": cf.name,
                "folder": cf.folder,
                "terms_ok": ok,
                "missing_terms": missing,
            }
        )

    kb_hits = [
        d
        for d in kb_docs
        if any(sub.lower() in str(d.get("name") or "").lower() for sub in expected)
    ]
    kb_detail = [
        {
            "name": d.get("name"),
            "document_id": d.get("document_id"),
            "status": d.get("status"),
            "collections_used": (d.get("extra") or {}).get("collections_used"),
        }
        for d in kb_hits
    ]

    mode_text = "text"
    mode_hybrid = "hybrid"
    search_text = _post(
        f"{base}/search",
        {"query": query, "kb_name": kb_name, "mode": mode_text},
    )
    search_hybrid = _post(
        f"{base}/search",
        {"query": query, "kb_name": kb_name, "mode": mode_hybrid},
    )
    text_hits = _extract_hits(search_text)
    hybrid_hits = _extract_hits(search_hybrid)

    route_text = _route_plan(query, "text")
    route_hybrid = _route_plan(query, "hybrid")

    failure_class = _classify_failure(
        row,
        corpus_hits,
        kb_hits,
        text_hits,
        hybrid_hits,
        route_text,
        route_hybrid,
    )

    pipeline = _local_pipeline_preview(query)
    steps_text = _parse_api_steps(search_text.get("steps") or [])
    steps_hybrid = _parse_api_steps(search_hybrid.get("steps") or [])

    return {
        "id": row.get("id"),
        "workflow": row.get("workflow"),
        "query": query,
        "gold": {
            "must_include_terms": terms,
            "expected_doc_name_substrings": expected,
            "route_hint": row.get("route_hint") or {},
            "eval_search_mode": resolve_search_mode(row),
        },
        "corpus": corpus_detail,
        "kb": kb_detail,
        "route_plan_text": route_text,
        "route_plan_hybrid": route_hybrid,
        "retrieval_text": text_hits,
        "retrieval_hybrid": hybrid_hits,
        "pipeline": pipeline,
        "api_steps_text": search_text.get("steps") or [],
        "api_steps_hybrid": search_hybrid.get("steps") or [],
        "api_stages_text": steps_text,
        "api_stages_hybrid": steps_hybrid,
        "failure_class": failure_class,
    }


def _render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Biomed retrieval diagnosis",
        "",
        f"- timestamp: {report['timestamp']}",
        f"- kb_name: {report['kb_name']}",
        f"- queries: {len(report['diagnoses'])}",
        "",
    ]
    for d in report["diagnoses"]:
        lines.extend(
            [
                f"## {d['id']} — `{d['failure_class']}`",
                "",
                f"**Query:** {d['query']}",
                f"**Workflow:** {d.get('workflow')}",
                "",
                "**Gold:**",
                f"- expected: `{d['gold']['expected_doc_name_substrings']}`",
                f"- terms: `{d['gold']['must_include_terms']}`",
                f"- eval mode: `{d['gold']['eval_search_mode']}`",
                "",
            ]
        )
        if d["corpus"]:
            lines.append("**Corpus matches:**")
            for c in d["corpus"]:
                lines.append(f"- `{c['file']}` ({c['folder']}) terms_ok={c['terms_ok']}")
        else:
            lines.append("**Corpus matches:** none")
        lines.append("")
        if d["kb"]:
            lines.append("**KB documents:**")
            for k in d["kb"]:
                lines.append(
                    f"- `{k['name']}` status={k['status']} collections={k['collections_used']}"
                )
        else:
            lines.append("**KB documents:** none")
        lines.append("")
        pipe = d.get("pipeline") or {}
        if pipe:
            lines.append("**Pipeline (local preview):**")
            lines.append(f"- intent workflow: `{pipe.get('retrieval_intent', {}).get('workflow')}`")
            lines.append(
                f"- section cues: `{pipe.get('retrieval_intent', {}).get('section_cues')}`"
            )
            lines.append(f"- rerank policy: `{pipe.get('rerank_policy')}`")
            lines.append(f"- merged rerank model: `{pipe.get('merged_rerank_model')}`")
            expand = pipe.get("dense_expand") or {}
            lines.append(f"- dense query: `{expand.get('dense_query', '')[:120]}`")
            lines.append(f"- sparse terms: `{expand.get('sparse_terms')}`")
            lines.append("")
        for label, key in (("text", "api_stages_text"), ("hybrid", "api_stages_hybrid")):
            stages = d.get(key) or {}
            if stages:
                lines.append(f"**API stages ({label}):** `{stages.get('stages')}`")
                if stages.get("merged_rerank"):
                    mr = stages["merged_rerank"]
                    lines.append(f"- merged rerank model: `{mr.get('model')}`")
                lines.append("")
        lines.append("**Top text hits:**")
        for i, h in enumerate(d["retrieval_text"][:5], start=1):
            preview = (h.get("content_preview") or "")[:80]
            path = h.get("path") or ""
            lines.append(
                f"{i}. `{h.get('file_name')}` path=`{path}` score={h.get('score')} — {preview}"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument(
        "--queries",
        default=str(DATASETS / "eval_queries.smoke.jsonl"),
    )
    ap.add_argument(
        "--ids",
        default=",".join(DEFAULT_FAILED_IDS),
        help="Comma-separated query ids to diagnose",
    )
    ap.add_argument(
        "--report",
        default="",
        help="Optional smoke JSON report to auto-pick failed ids",
    )
    args = ap.parse_args()

    qmap = _load_queries(Path(args.queries))
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]

    if args.report:
        rep = json.loads(Path(args.report).read_text(encoding="utf-8"))
        auto = [
            str(d["id"])
            for d in rep.get("details") or []
            if float(d.get("hit") or 0) < 1.0 or float(d.get("term_coverage") or 1) < 1.0
        ]
        if auto:
            ids = auto

    base = args.base_url.rstrip("/")
    corpus_files = scan_corpus()
    kb_docs = _fetch_kb_documents(base, args.kb_name)

    diagnoses: list[dict[str, Any]] = []
    for qid in ids:
        row = qmap.get(qid)
        if not row:
            print("skip unknown id", qid)
            continue
        print("diagnose", qid)
        diagnoses.append(
            diagnose_row(
                row,
                base=base,
                kb_name=args.kb_name,
                corpus_files=corpus_files,
                kb_docs=kb_docs,
            )
        )

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "kb_name": args.kb_name,
        "query_ids": ids,
        "diagnoses": diagnoses,
        "summary": {
            c: sum(1 for d in diagnoses if d["failure_class"] == c)
            for c in sorted({d["failure_class"] for d in diagnoses})
        },
    }

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = RESULTS / f"diagnosis_smoke8_{stamp}.json"
    md_path = RESULTS / f"diagnosis_smoke8_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_md(report), encoding="utf-8")
    print("summary", report["summary"])
    print("wrote", json_path)
    print("wrote", md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
