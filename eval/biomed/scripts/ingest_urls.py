#!/usr/bin/env python3
"""Batch-ingest manifest URL lists into kb_name=hutchmed via POST /ingest."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML required: uv sync") from exc

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST = ROOT / "eval" / "biomed" / "corpus" / "manifest.yaml"
USER_AGENT = "eagle-rag-biomed-ingest-urls/1.0"


def _load_manifest(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _collect_urls(cfg: dict[str, Any], sections: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for section in sections:
        for item in cfg.get(section) or []:
            url = str(item.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            out.append(item)
    return out


def _post_ingest(base: str, kb_name: str, url: str) -> tuple[int, dict[str, Any]]:
    data = urllib.parse.urlencode({"url": url, "kb_name": kb_name}).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/ingest",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": USER_AGENT},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            payload = json.loads(resp.read().decode())
            return resp.getcode() or 200, payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {"detail": body[:500]}
        return exc.code, payload


def _poll_jobs(base: str, job_ids: list[str], *, timeout_sec: int, interval_sec: float) -> int:
    pending = {jid for jid in job_ids if jid}
    if not pending:
        return 0
    failed = 0
    deadline = time.time() + timeout_sec
    while pending and time.time() < deadline:
        done: list[str] = []
        for job_id in list(pending):
            req = urllib.request.Request(
                f"{base.rstrip('/')}/tasks/{job_id}",
                headers={"User-Agent": USER_AGENT},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    audit = json.loads(resp.read().decode())
            except Exception as exc:  # noqa: BLE001
                print(f"poll {job_id[:8]} error: {exc}")
                continue
            state = str(audit.get("status") or audit.get("state") or "").lower()
            if state in {"success", "succeeded", "completed", "failed", "error", "dead"}:
                print(f"job {job_id[:8]} -> {state}")
                if state in {"failed", "error", "dead"}:
                    failed += 1
                done.append(job_id)
        for job_id in done:
            pending.discard(job_id)
        if pending:
            time.sleep(interval_sec)
    if pending:
        print(f"timeout: {len(pending)} jobs still pending")
        failed += len(pending)
    return failed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    ap.add_argument(
        "--section",
        action="append",
        default=None,
        help="Manifest list key (default: news_urls). Repeatable.",
    )
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument("--limit", type=int, default=0, help="0 = all URLs in selected sections")
    ap.add_argument("--concurrency-gap", type=float, default=0.5)
    ap.add_argument("--poll", action="store_true", help="Wait for ingest jobs to finish")
    ap.add_argument("--poll-timeout", type=int, default=900)
    ap.add_argument("--poll-interval", type=float, default=5.0)
    args = ap.parse_args()

    if not args.manifest.is_file():
        print("manifest not found:", args.manifest)
        return 1

    sections = args.section or ["news_urls"]
    items = _collect_urls(_load_manifest(args.manifest), sections)
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("no URLs in sections", sections)
        return 1

    submitted = dedup = failed = 0
    job_ids: list[str] = []
    for i, item in enumerate(items, start=1):
        url = str(item["url"])
        title = str(item.get("title") or url)
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        code, payload = _post_ingest(args.base_url, args.kb_name, url)
        if code in (200, 201) and isinstance(payload, dict):
            if payload.get("dedup_hit"):
                doc_id = str(payload.get("document_id", ""))[:8]
                print(f"[{i}/{len(items)}] DEDUP {slug} ({title[:48]}) -> {doc_id}")
                dedup += 1
            else:
                job_id = str(payload.get("job_id") or "")
                print(
                    f"[{i}/{len(items)}] {slug} ({title[:48]}) -> "
                    f"{payload.get('status')} {job_id[:8] if job_id else ''}"
                )
                submitted += 1
                if job_id:
                    job_ids.append(job_id)
        else:
            print(f"[{i}/{len(items)}] FAIL {slug}: HTTP {code} {payload}")
            failed += 1
        time.sleep(args.concurrency_gap)

    print(f"submitted {submitted}/{len(items)} dedup {dedup} failed {failed}")
    if args.poll and job_ids:
        poll_failed = _poll_jobs(
            args.base_url,
            job_ids,
            timeout_sec=args.poll_timeout,
            interval_sec=args.poll_interval,
        )
        failed += poll_failed
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
