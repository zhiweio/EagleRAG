#!/usr/bin/env python3
"""Biomed deploy smoke: health → KB → ingest sample → poll → search check."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "assets" / "biomed" / "hutchmed"
FIXTURES = ROOT / "eval" / "biomed" / "fixtures"


def _req(
    method: str,
    url: str,
    *,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
    h = {"User-Agent": "eagle-rag-biomed-e2e/1.0", **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            body = resp.read()
            code = resp.getcode() or 200
    except urllib.error.HTTPError as exc:
        body = exc.read()
        code = exc.code
    try:
        return code, json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return code, body.decode("utf-8", errors="replace")


def _multipart(file_path: Path, kb_name: str) -> tuple[bytes, str]:
    boundary = "----EagleBiomedBoundary7MA4YWxkTrZu0gW"
    filename = file_path.name
    content = file_path.read_bytes()
    parts = [
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="kb_name"\r\n\r\n{kb_name}\r\n'
        ).encode(),
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + content
        + b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _sample_files(limit: int, *, include_fixtures: bool) -> list[Path]:
    files: list[Path] = []
    if CORPUS.exists():
        for sub in ("compounds", "abstracts", "trials", "papers", "labels", "guidance", "company"):
            d = CORPUS / sub
            if d.is_dir():
                files.extend(sorted(p for p in d.iterdir() if p.is_file()))
    if include_fixtures and FIXTURES.exists():
        files.extend(sorted(FIXTURES.rglob("*.md")))
    out: list[Path] = []
    for path in files:
        if path.suffix.lower() in {".md", ".txt", ".pdf"}:
            out.append(path)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument("--ingest-limit", type=int, default=5)
    ap.add_argument("--poll-timeout", type=int, default=600)
    ap.add_argument(
        "--include-fixtures",
        action="store_true",
        help="Allow fixture files in ingest sample (default: corpus only)",
    )
    ap.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip ingest; only run health check and search smoke",
    )
    args = ap.parse_args()
    base = args.base_url.rstrip("/")

    print("== health/plugins ==")
    code, plugins = _req("GET", f"{base}/health/plugins")
    if code != 200 or not isinstance(plugins, dict):
        print("FAIL health/plugins", code, plugins)
        return 1
    ns = plugins.get("default_namespace") or plugins.get("plugin_namespace")
    print("namespace=", ns)
    if ns != "biomed":
        print("FAIL expected default_namespace=biomed")
        return 1

    print("== ensure KB ==")
    code, _ = _req(
        "POST",
        f"{base}/knowledge_bases",
        data=json.dumps(
            {
                "kb_name": args.kb_name,
                "display_name": "HUTCHMED Oncology R&D",
                "description": "Innovative oncology drug literature and DB matching",
                "theme": "emerald",
                "icon": "flask",
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    if code not in (201, 409):
        print("FAIL create KB", code)
        return 1
    print("KB ok", args.kb_name, "http", code)

    if not args.skip_ingest:
        samples = _sample_files(args.ingest_limit, include_fixtures=args.include_fixtures)
        if not samples:
            FIXTURES.mkdir(parents=True, exist_ok=True)
            sample = FIXTURES / "fruquintinib_overview.md"
            sample.write_text(
                "# Fruquintinib (HMPL-013)\n\n"
                "Selective VEGFR-1/2/3 inhibitor for metastatic colorectal cancer (mCRC). "
                "Also studied with sintilimab in renal cell carcinoma. "
                "Keywords: kinase, inhibitor, angiogenesis, pathway, receptor.\n",
                encoding="utf-8",
            )
            samples = [sample]
            print("WARN no corpus — using fixture; run task biomed:corpus for full set")

        job_ids: list[str] = []
        for path in samples:
            body, ctype = _multipart(path, args.kb_name)
            code, resp = _req(
                "POST",
                f"{base}/ingest",
                data=body,
                headers={"Content-Type": ctype},
                timeout=180,
            )
            status = resp.get("status") if isinstance(resp, dict) else resp
            if code == 200 and isinstance(resp, dict) and resp.get("dedup_hit"):
                print("ingest", path.name, code, "dedup", resp.get("document_id", "")[:8])
                continue
            print("ingest", path.name, code, status)
            if code >= 400:
                print("FAIL ingest", resp)
                return 1
            if isinstance(resp, dict) and resp.get("job_id"):
                job_ids.append(str(resp["job_id"]))

        deadline = time.time() + args.poll_timeout
        pending = set(job_ids)
        while pending and time.time() < deadline:
            done: list[str] = []
            for job_id in list(pending):
                code, audit = _req("GET", f"{base}/tasks/{job_id}")
                state = None
                if isinstance(audit, dict):
                    state = (audit.get("status") or audit.get("state") or "").lower()
                if state in {"success", "failed", "succeeded", "completed", "error", "dead"}:
                    print("job", job_id, state)
                    if state in {"failed", "error", "dead"}:
                        print("FAIL task", audit)
                        return 1
                    done.append(job_id)
            for job_id in done:
                pending.discard(job_id)
            if pending:
                time.sleep(3)
        if pending:
            print("FAIL timeout waiting for jobs", pending)
            return 1
    else:
        print("== skip ingest ==")

    print("== search ==")
    code, search = _req(
        "POST",
        f"{base}/search",
        data=json.dumps(
            {
                "query": "fruquintinib VEGFR metastatic colorectal cancer",
                "kb_name": args.kb_name,
                "mode": "text",
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    if code != 200:
        print("FAIL search", code, search)
        return 1
    sources: list[Any] = []
    if isinstance(search, dict):
        src = search.get("sources") or {}
        if isinstance(src, dict):
            sources = list(src.get("text") or [])
    print("search hits", len(sources))
    print("E2E OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
