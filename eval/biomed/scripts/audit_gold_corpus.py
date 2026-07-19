#!/usr/bin/env python3
"""Audit eval gold labels against the HUTCHMED corpus; emit aligned subsets."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
DATASETS = SCRIPTS.parent / "datasets"
RESULTS = SCRIPTS.parent / "results"

sys.path.insert(0, str(SCRIPTS))

from corpus_index import audit_query_row, scan_corpus  # noqa: E402


def _load_queries(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _render_md(audits: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# Gold / corpus alignment audit",
        "",
        f"- total queries: {summary['total']}",
        f"- aligned: {summary['aligned']}",
        f"- partial: {summary['partial']}",
        f"- absent: {summary['absent']}",
        "",
        "## By workflow",
        "",
        "| workflow | aligned | partial | absent |",
        "| --- | --- | --- | --- |",
    ]
    for wf, counts in sorted(summary["by_workflow"].items()):
        lines.append(
            f"| {wf} | {counts.get('aligned', 0)} | "
            f"{counts.get('partial', 0)} | {counts.get('absent', 0)} |"
        )
    lines.extend(["", "## Partial / absent queries", ""])
    for a in audits:
        if a["alignment"] == "aligned":
            continue
        lines.append(
            f"- `{a['id']}` ({a['workflow']}): **{a['alignment']}** — "
            f"expected {a['expected_doc_name_substrings']}"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--queries",
        default=str(DATASETS / "eval_queries.jsonl"),
    )
    ap.add_argument(
        "--smoke-queries",
        default=str(DATASETS / "eval_queries.smoke.jsonl"),
    )
    args = ap.parse_args()

    corpus = scan_corpus()
    rows = _load_queries(Path(args.queries))
    audits = [audit_query_row(r, corpus) for r in rows]

    counts = Counter(a["alignment"] for a in audits)
    by_workflow: dict[str, Counter[str]] = {}
    for a in audits:
        by_workflow.setdefault(str(a["workflow"]), Counter())[str(a["alignment"])] += 1

    summary = {
        "total": len(audits),
        "aligned": counts.get("aligned", 0),
        "partial": counts.get("partial", 0),
        "absent": counts.get("absent", 0),
        "by_workflow": {wf: dict(c) for wf, c in by_workflow.items()},
    }

    aligned_ids = {a["id"] for a in audits if a["alignment"] == "aligned"}
    aligned_rows = [r for r in rows if r["id"] in aligned_ids]

    smoke_rows = _load_queries(Path(args.smoke_queries))
    smoke_aligned = [r for r in smoke_rows if r["id"] in aligned_ids]

    aligned_path = DATASETS / "eval_queries.aligned.jsonl"
    smoke_aligned_path = DATASETS / "eval_queries.smoke.aligned.jsonl"
    _write_jsonl(aligned_path, aligned_rows)
    _write_jsonl(smoke_aligned_path, smoke_aligned)

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    json_path = RESULTS / f"gold_audit_{stamp}.json"
    md_path = RESULTS / f"gold_audit_{stamp}.md"
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "summary": summary,
        "audits": audits,
        "aligned_output": str(aligned_path),
        "smoke_aligned_output": str(smoke_aligned_path),
        "aligned_count": len(aligned_rows),
        "smoke_aligned_count": len(smoke_aligned),
    }
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(_render_md(audits, summary), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"wrote {aligned_path} ({len(aligned_rows)} queries)")
    print(f"wrote {smoke_aligned_path} ({len(smoke_aligned)} queries)")
    print("wrote", json_path)
    print("wrote", md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
