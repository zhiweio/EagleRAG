#!/usr/bin/env python3
"""Oracle eval: verify gold filenames are findable via corpus lexical match."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
DATASETS = ROOT / "eval" / "biomed" / "datasets"
RESULTS = ROOT / "eval" / "biomed" / "results"

sys.path.insert(0, str(SCRIPTS))

from corpus_index import match_corpus_files, scan_corpus  # noqa: E402
from metrics import substring_hit  # noqa: E402


def _load_queries(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--queries",
        default=str(DATASETS / "eval_queries.aligned.jsonl"),
    )
    ap.add_argument("--corpus-root", default=str(ROOT / "assets" / "biomed" / "hutchmed"))
    ap.add_argument("--fail-under", type=float, default=0.95)
    ap.add_argument("--no-fail", action="store_true")
    args = ap.parse_args()

    files = scan_corpus(Path(args.corpus_root))
    queries = _load_queries(Path(args.queries))
    hits = 0
    details: list[dict] = []
    for row in queries:
        needles = list(row.get("expected_doc_name_substrings") or [])
        matched = match_corpus_files(files, needles)
        blob = " ".join(cf.name for cf in matched)
        ok = substring_hit(needles, [blob], len(needles) or 1) if needles else bool(matched)
        hits += int(ok)
        details.append(
            {
                "id": row.get("id"),
                "needles": needles,
                "matched_files": [cf.name for cf in matched],
                "oracle_hit": ok,
            }
        )

    total = len(queries) or 1
    rate = hits / total
    report = {
        "oracle_hit_rate": rate,
        "hits": hits,
        "total": len(queries),
        "details": details,
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / "oracle_eval_latest.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"oracle_hit_rate": rate, "path": str(out)}, indent=2))
    if not args.no_fail and rate < args.fail_under:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
