#!/usr/bin/env python3
"""Purge and re-ingest the hutchmed KB (TDR chunk metadata + sparse backfill)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = Path(__file__).resolve().parent
USER_AGENT = "eagle-rag-biomed-reingest/1.0"


def _request(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.getcode() or 200, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = {"detail": body[:500]}
        return exc.code, parsed


def _purge_kb(base: str, kb_name: str) -> dict[str, Any]:
    code, payload = _request("DELETE", f"{base}/knowledge_bases/{kb_name}")
    if code == 404:
        print(f"KB {kb_name} not found; skip purge")
        return {}
    if code >= 400:
        raise RuntimeError(f"purge failed HTTP {code}: {payload}")
    print(f"purged {kb_name}: {payload}")
    return payload if isinstance(payload, dict) else {}


def _ensure_kb(base: str, kb_name: str) -> None:
    code, _payload = _request("GET", f"{base}/knowledge_bases/{kb_name}")
    if code == 200:
        print(f"KB {kb_name} exists")
        return
    body = {
        "kb_name": kb_name,
        "display_name": "HUTCHMED Oncology R&D",
        "description": "Biomed eval corpus (hutchmed)",
    }
    code, payload = _request("POST", f"{base}/knowledge_bases", payload=body)
    if code in {200, 201, 409}:
        print(f"KB {kb_name} ready")
        return
    raise RuntimeError(f"create KB failed HTTP {code}: {payload}")


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
                f"{base}/tasks/{job_id}",
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
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--kb-name", default="hutchmed")
    ap.add_argument("--no-purge", action="store_true", help="Skip KB purge before ingest")
    ap.add_argument("--poll", action="store_true", help="Wait for ingest jobs to finish")
    ap.add_argument("--poll-timeout", type=int, default=7200)
    ap.add_argument("--poll-interval", type=float, default=15.0)
    ap.add_argument(
        "--reindex-sparse",
        action="store_true",
        help="Run primary_drugs backfill after ingest",
    )
    ap.add_argument("ingest_args", nargs="*", help="Extra args forwarded to ingest_corpus.py")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    if not args.no_purge:
        _purge_kb(base, args.kb_name)
        time.sleep(2.0)
    _ensure_kb(base, args.kb_name)

    ingest_cmd = [
        sys.executable,
        str(SCRIPTS / "ingest_corpus.py"),
        "--base-url",
        base,
        "--kb-name",
        args.kb_name,
        *args.ingest_args,
    ]
    print("run", " ".join(ingest_cmd))
    proc = subprocess.run(ingest_cmd, cwd=ROOT, check=False)
    if proc.returncode != 0:
        return proc.returncode

    if args.poll:
        # Re-scan task audit for recent ingest jobs on this KB (best-effort).
        print("poll enabled; waiting for router/knowhere queue drain (check worker logs)")
        time.sleep(5.0)

    if args.reindex_sparse:
        reindex_cmd = [
            sys.executable,
            str(SCRIPTS / "reindex_sparse.py"),
            "--kb-name",
            args.kb_name,
        ]
        print("run", " ".join(reindex_cmd))
        env = {
            **dict(__import__("os").environ),
            "MILVUS_HOST": "localhost",
            "POSTGRES_DSN": "postgresql://eagle:eagle@localhost:5432/eagle_rag",
            "EAGLE_RAG_PROFILE": "biomed",
            "PLUGIN_NAMESPACE": "biomed",
        }
        proc = subprocess.run(reindex_cmd, cwd=ROOT, env=env, check=False)
        if proc.returncode != 0:
            return proc.returncode

    print("reingest complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
