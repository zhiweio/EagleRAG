#!/usr/bin/env python3
"""Batch-ingest downloaded corpus files into kb_name=hutchmed via POST /ingest."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "assets" / "biomed" / "hutchmed"
FIXTURES = ROOT / "eval" / "biomed" / "fixtures"


def _multipart(file_path: Path, kb_name: str) -> tuple[bytes, str]:
    boundary = "----EagleBiomedIngestBoundary"
    content = file_path.read_bytes()
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="kb_name"\r\n\r\n{kb_name}\r\n'
        ).encode()
        + (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
        + f"--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument("--limit", type=int, default=0, help="0 = all files")
    ap.add_argument("--concurrency-gap", type=float, default=0.5)
    ap.add_argument(
        "--include-fixtures",
        action="store_true",
        help="Also ingest eval/biomed/fixtures (default: corpus only)",
    )
    args = ap.parse_args()

    files: list[Path] = []
    if args.include_fixtures and FIXTURES.is_dir():
        files.extend(sorted(FIXTURES.glob("*.md")))
    if CORPUS.is_dir():
        for sub in ("compounds", "abstracts", "trials", "labels", "guidance", "company", "papers"):
            d = CORPUS / sub
            if d.is_dir():
                files.extend(sorted(p for p in d.iterdir() if p.is_file()))
    if args.limit:
        files = files[: args.limit]
    if not files:
        print("no files under", CORPUS)
        return 1

    base = args.base_url.rstrip("/")
    ok = skipped = 0
    seen_sha: set[str] = set()
    for i, path in enumerate(files, start=1):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest in seen_sha:
            print(f"[{i}/{len(files)}] SKIP {path.name} (duplicate sha256 in batch)")
            skipped += 1
            continue
        seen_sha.add(digest)
        body, ctype = _multipart(path, args.kb_name)
        req = urllib.request.Request(
            f"{base}/ingest",
            data=body,
            headers={"Content-Type": ctype, "User-Agent": "eagle-rag-biomed-ingest/1.0"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                code = resp.getcode()
                payload = json.loads(resp.read().decode())
            if code == 200 and payload.get("dedup_hit"):
                doc_id = str(payload.get("document_id", ""))[:8]
                print(f"[{i}/{len(files)}] DEDUP {path.name} -> existing {doc_id}")
                skipped += 1
            else:
                status = payload.get("status")
                job_id = payload.get("job_id")
                print(f"[{i}/{len(files)}] {path.name} -> {status} {job_id}")
                ok += 1
        except urllib.error.HTTPError as exc:
            print(f"[{i}/{len(files)}] FAIL {path.name}: {exc.code} {exc.read()[:200]!r}")
        time.sleep(args.concurrency_gap)
    print(f"submitted {ok}/{len(files)} skipped {skipped}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
