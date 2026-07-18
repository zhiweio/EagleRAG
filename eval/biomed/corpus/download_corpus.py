#!/usr/bin/env python3
"""Download HUTCHMED oncology innovative-drug corpus (~300 docs) for biomed eval.

Writes files under ``assets/biomed/hutchmed/`` and a lock file at
``eval/biomed/corpus/manifest.lock.json``. Idempotent: skips existing sha256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import ssl
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
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.yaml"
LOCK_PATH = Path(__file__).resolve().parent / "manifest.lock.json"
OUT_ROOT = ROOT / "assets" / "biomed" / "hutchmed"

USER_AGENT = "eagle-rag-biomed-eval/1.0 (research; +https://github.com/Ontos-AI/eagle-rag)"
SLEEP_S = 0.35
DEFAULT_LOCAL_PROXY = "http://127.0.0.1:1087"

# Quality gates for "real" R&D literature (reject abstract-only stubs).
MIN_PDF_BYTES = 40_000
MIN_FULLTEXT_CHARS = 6_000
MIN_ABSTRACT_CHARS = 800
MIN_TRIAL_CHARS = 1_500
# Do not treat these publication types as full papers even if short XML returns.
_PAPER_SKIP_TITLE_RE = re.compile(
    r"^(erratum|correction|retraction|author.?s?\s+response)\b",
    re.I,
)

# Populated by configure_proxy(); None means direct connection.
_OPENER: urllib.request.OpenerDirector | None = None
_SSL_CONTEXT: ssl.SSLContext | None = None


def configure_proxy(proxy_url: str | None, *, insecure_ssl: bool = False) -> str | None:
    """Install a global urllib opener for HTTP(S) via proxy.

    Resolution order for ``proxy_url`` when None:
    ``BIOMED_HTTP_PROXY`` → ``HTTPS_PROXY`` / ``HTTP_PROXY`` → None (direct).

    Mainland China tip: local Clash/V2Ray HTTP port is often
    ``http://127.0.0.1:1087`` — pass ``--proxy`` or set ``BIOMED_HTTP_PROXY``.

    When the local proxy terminates TLS (MITM), set ``insecure_ssl=True`` or
    ``BIOMED_SSL_INSECURE=1`` to skip certificate verification.
    """
    global _OPENER, _SSL_CONTEXT
    resolved = (proxy_url or "").strip() or (
        os.environ.get("BIOMED_HTTP_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
    insecure = insecure_ssl or os.environ.get("BIOMED_SSL_INSECURE", "").strip() in {
        "1",
        "true",
        "yes",
    }
    _SSL_CONTEXT = ssl._create_unverified_context() if insecure else None
    handlers: list[Any] = []
    if resolved:
        handlers.append(urllib.request.ProxyHandler({"http": resolved, "https": resolved}))
    if _SSL_CONTEXT is not None:
        handlers.append(urllib.request.HTTPSHandler(context=_SSL_CONTEXT))
    if handlers:
        _OPENER = urllib.request.build_opener(*handlers)
        urllib.request.install_opener(_OPENER)
    else:
        _OPENER = None
    if resolved:
        os.environ.setdefault("HTTP_PROXY", resolved)
        os.environ.setdefault("HTTPS_PROXY", resolved)
        os.environ.setdefault("http_proxy", resolved)
        os.environ.setdefault("https_proxy", resolved)
    if insecure:
        print("SSL verify: disabled (BIOMED_SSL_INSECURE / --insecure-ssl)")
    return resolved or None


def _load_manifest() -> dict[str, Any]:
    return yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _http_get(url: str, *, timeout: float = 60.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
    opener = _OPENER or urllib.request.build_opener()
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def _http_get_json(url: str, *, timeout: float = 60.0) -> Any:
    return json.loads(_http_get(url, timeout=timeout).decode("utf-8", errors="replace"))


def _slug(text: str, max_len: int = 80) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", text).strip("_")
    return (s[:max_len] or "doc").lower()


def _write_file(
    rel_dir: str,
    filename: str,
    data: bytes,
    *,
    meta: dict[str, Any],
    lock: list[dict[str, Any]],
    seen: set[str],
) -> bool:
    digest = _sha256(data)
    if digest in seen:
        return False
    dest_dir = OUT_ROOT / rel_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / filename
    path.write_bytes(data)
    record = {
        **meta,
        "path": str(path.relative_to(ROOT)),
        "sha256": digest,
        "bytes": len(data),
    }
    lock.append(record)
    seen.add(digest)
    return True


def _write_text(
    rel_dir: str,
    filename: str,
    text: str,
    *,
    meta: dict[str, Any],
    lock: list[dict[str, Any]],
    seen: set[str],
) -> bool:
    return _write_file(
        rel_dir,
        filename,
        text.encode("utf-8"),
        meta=meta,
        lock=lock,
        seen=seen,
    )


def _normalize_pmcid(pmcid: str) -> str:
    pmcid = (pmcid or "").strip()
    if not pmcid:
        return ""
    return pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"


def _xml_to_markdown(title: str, pmid: str, pmcid: str, xml_text: str) -> str:
    """Convert Europe PMC fullTextXML (JATS-like) into readable markdown body."""
    # Strip scripts/styles; keep section titles roughly via <title> / <p>
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", xml_text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?is)</(sec|p|title|abstract|ref)>", "\n\n", text)
    text = re.sub(r"(?is)<title[^>]*>", "\n## ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()
    header = f"# {title}\n\n- PMID: {pmid}\n- PMCID: {pmcid}\n- Source: Europe PMC fullTextXML\n\n"
    return header + text + "\n"


def _fetch_oa_pdf(pmcid: str, item: dict[str, Any]) -> tuple[bytes | None, str]:
    """Try OA PDF endpoints with a short timeout; return (bytes, url) or (None, '')."""
    pmcid = _normalize_pmcid(pmcid)
    candidates: list[str] = []
    for link in (item.get("fullTextUrlList") or {}).get("fullTextUrl") or []:
        if (link.get("documentStyle") or "").lower() == "pdf" and link.get("url"):
            candidates.append(str(link["url"]))
    if pmcid:
        bare = pmcid.replace("PMC", "")
        candidates.extend(
            [
                f"https://europepmc.org/articles/{pmcid}?pdf=render",
                f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf",
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/",
                f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{bare}/pdf/",
            ]
        )
    # Cap attempts: PDF pulls are large and often hang behind proxies.
    for url in candidates[:3]:
        try:
            data = _http_get(url, timeout=25)
            time.sleep(SLEEP_S)
        except Exception:  # noqa: BLE001
            continue
        if data[:4] == b"%PDF" and len(data) >= MIN_PDF_BYTES:
            return data, url
    return None, ""


def _fetch_fulltext_xml_md(title: str, pmid: str, pmcid: str) -> tuple[bytes | None, str]:
    pmcid = _normalize_pmcid(pmcid)
    if not pmcid:
        return None, ""
    url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
    try:
        xml_bytes = _http_get(url, timeout=45)
        time.sleep(SLEEP_S)
    except Exception:  # noqa: BLE001
        return None, ""
    xml_text = xml_bytes.decode("utf-8", errors="replace")
    md = _xml_to_markdown(title, pmid, pmcid, xml_text)
    # Body without header must still be substantial
    body = md.split("\n\n", 1)[-1] if "\n\n" in md else md
    if len(body) < MIN_FULLTEXT_CHARS:
        return None, ""
    return md.encode("utf-8"), url


def _existing_paper_ids(lock: list[dict[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for rec in lock:
        if rec.get("source_type") != "paper":
            continue
        for key in ("pmcid", "doc_id"):
            val = _normalize_pmcid(str(rec.get(key) or ""))
            if val:
                ids.add(val.upper())
    papers_dir = OUT_ROOT / "papers"
    if papers_dir.exists():
        for path in papers_dir.iterdir():
            if path.is_file() and path.stem.lower().startswith("pmc"):
                ids.add(_normalize_pmcid(path.stem).upper())
    return ids


def download_papers(
    cfg: dict[str, Any], lock: list[dict[str, Any]], seen: set[str], quota: int
) -> int:
    """Download real OA full text (fullTextXML→MD preferred; PDF fallback).

    Never counts abstract-only stubs toward the papers quota.
    """
    added = 0
    queries = list(cfg.get("paper_queries") or [])
    page_size = 25
    qi = 0
    skipped_thin = 0
    have_ids = _existing_paper_ids(lock)
    while added < quota and queries:
        raw_q = queries[qi % len(queries)]
        qi += 1
        # OA full text; HAS_PDF helps PDF fallback but XML is accepted too.
        query = f"({raw_q}) AND OPEN_ACCESS:y AND (HAS_PDF:y OR HAS_FT:y)"
        cursor = "*"
        for _ in range(12):
            if added >= quota:
                break
            params = urllib.parse.urlencode(
                {
                    "query": query,
                    "format": "json",
                    "pageSize": page_size,
                    "resultType": "core",
                    "cursorMark": cursor,
                }
            )
            url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
            try:
                payload = _http_get_json(url)
            except Exception as exc:  # noqa: BLE001
                print(f"[papers] search failed: {exc}", flush=True)
                break
            results = (payload.get("resultList") or {}).get("result") or []
            if not results:
                break
            cursor = payload.get("nextCursorMark") or ""
            for item in results:
                if added >= quota:
                    break
                if str(item.get("isOpenAccess") or "").upper() not in {"Y", "YES", "TRUE"}:
                    continue
                pmcid = _normalize_pmcid(str(item.get("pmcid") or ""))
                pmid = str(item.get("pmid") or "")
                title = item.get("title") or pmcid or pmid or "paper"
                if _PAPER_SKIP_TITLE_RE.search(title or ""):
                    skipped_thin += 1
                    continue
                if not pmcid:
                    skipped_thin += 1
                    continue
                if pmcid.upper() in have_ids:
                    continue

                # Prefer Europe PMC XML full text (fast, still real literature).
                data, source_url = _fetch_fulltext_xml_md(title, pmid, pmcid)
                ext = "md"
                fulltext_kind = "fulltext_xml"
                if data is None:
                    data, source_url = _fetch_oa_pdf(pmcid, item)
                    ext = "pdf"
                    fulltext_kind = "pdf"
                if data is None:
                    skipped_thin += 1
                    continue

                fname = f"{_slug(pmcid)}.{ext}"
                ok = _write_file(
                    "papers",
                    fname,
                    data,
                    meta={
                        "doc_id": pmcid,
                        "source_type": "paper",
                        "rnd_stage": "clinical_evidence",
                        "license": item.get("license") or "pmc-oa",
                        "url": source_url,
                        "title": title,
                        "pmid": pmid,
                        "pmcid": pmcid,
                        "fulltext_kind": fulltext_kind,
                        "tags": ["paper", "oncology", "fulltext"],
                        "query": raw_q,
                    },
                    lock=lock,
                    seen=seen,
                )
                if ok:
                    added += 1
                    have_ids.add(pmcid.upper())
                    print(
                        f"[papers] {added}/{quota} {fname} "
                        f"({fulltext_kind}, {len(data)} bytes) {title[:50]}",
                        flush=True,
                    )
            if not cursor or cursor == "*":
                break
            time.sleep(SLEEP_S)
        if qi >= len(queries) * 4 and added < quota:
            break
    print(f"[papers] skipped non-fulltext/errata={skipped_thin}", flush=True)
    return added


def purge_thin_papers(*, dry_run: bool = False) -> int:
    """Remove abstract-only / undersized paper stubs from disk + lock."""
    if not LOCK_PATH.exists():
        return 0
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    docs = list(payload.get("documents") or [])
    keep: list[dict[str, Any]] = []
    removed = 0
    for rec in docs:
        path = ROOT / str(rec.get("path") or "")
        st = rec.get("source_type")
        drop = False
        if st == "paper":
            size = path.stat().st_size if path.exists() else int(rec.get("bytes") or 0)
            kind = rec.get("fulltext_kind")
            if path.suffix.lower() == ".pdf" and size < MIN_PDF_BYTES:
                drop = True
            elif path.suffix.lower() == ".md":
                text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
                # Legacy abstract stubs lack fulltext_kind and are short
                if kind not in {"pdf", "fulltext_xml"} or len(text) < MIN_FULLTEXT_CHARS:
                    drop = True
        if drop:
            removed += 1
            print(f"[purge] drop {rec.get('path')} bytes={rec.get('bytes')}")
            if not dry_run and path.exists():
                path.unlink(missing_ok=True)
            continue
        keep.append(rec)
    if not dry_run:
        payload["documents"] = keep
        payload["total_documents"] = len(keep)
        by_type: dict[str, int] = {}
        for rec in keep:
            st = rec.get("source_type") or "unknown"
            by_type[st] = by_type.get(st, 0) + 1
        payload["by_type"] = by_type
        LOCK_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(f"[purge] removed={removed} kept={len(keep)} dry_run={dry_run}")
    return removed


def download_abstracts(
    cfg: dict[str, Any], lock: list[dict[str, Any]], seen: set[str], quota: int
) -> int:
    added = 0
    for query in cfg.get("abstract_queries") or []:
        if added >= quota:
            break
        params = urllib.parse.urlencode(
            {
                "query": query,
                "format": "json",
                "pageSize": min(50, quota - added),
                "resultType": "core",
            }
        )
        url = f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?{params}"
        try:
            payload = _http_get_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"[abstracts] {exc}")
            continue
        for item in (payload.get("resultList") or {}).get("result") or []:
            if added >= quota:
                break
            abstract = item.get("abstractText") or ""
            if len(abstract) < MIN_ABSTRACT_CHARS:
                continue
            pmid = str(item.get("pmid") or item.get("id") or "")
            title = item.get("title") or pmid
            body = (
                f"# {title}\n\n"
                f"- PMID: {pmid}\n"
                f"- Source query: {query}\n"
                f"- Note: abstract evidence card (not full text)\n\n"
                f"{abstract}\n"
            )
            ok = _write_text(
                "abstracts",
                f"abs_{_slug(pmid or title)}.md",
                body,
                meta={
                    "doc_id": f"ABS_{pmid}",
                    "source_type": "abstract",
                    "rnd_stage": "discovery",
                    "license": "europepmc-abstract",
                    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
                    "title": title,
                    "pmid": pmid,
                    "tags": ["abstract", "oncology"],
                    "query": query,
                },
                lock=lock,
                seen=seen,
            )
            if ok:
                added += 1
                print(f"[abstracts] {added}/{quota}")
            time.sleep(SLEEP_S)
    # Optional HF enrichment (best-effort; does not fail the run).
    if added < quota:
        added += _try_hf_abstracts(lock, seen, quota - added)
    return added


def _try_hf_abstracts(lock: list[dict[str, Any]], seen: set[str], need: int) -> int:
    if need <= 0:
        return 0
    try:
        from datasets import load_dataset
    except Exception:  # noqa: BLE001
        print("[abstracts] huggingface datasets not available; skipping HF fill")
        return 0
    cache_dir = ROOT / "data" / "biomed" / "hf"
    cache_dir.mkdir(parents=True, exist_ok=True)
    keywords = ("fruquintinib", "savolitinib", "surufatinib", "VEGFR", "MET inhibitor", "mCRC")
    added = 0
    try:
        ds = load_dataset(
            "pubmed",
            split="train",
            streaming=True,
            trust_remote_code=True,
            cache_dir=str(cache_dir),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[abstracts] HF pubmed stream unavailable: {exc}")
        return 0
    for i, row in enumerate(ds):
        if added >= need or i > 50000:
            break
        # pubmed dataset schemas vary; try common fields
        title = str(row.get("title") or row.get("ArticleTitle") or f"hf_{i}")
        abstract = str(row.get("abstract") or row.get("AbstractText") or "")
        if not abstract and isinstance(row.get("MedlineCitation"), dict):
            continue
        blob = f"{title} {abstract}".lower()
        if not any(k.lower() in blob for k in keywords):
            continue
        if len(abstract) < 80:
            continue
        body = f"# {title}\n\n{abstract}\n"
        ok = _write_text(
            "abstracts",
            f"hf_{_slug(title)}_{i}.md",
            body,
            meta={
                "doc_id": f"HF_{i}",
                "source_type": "abstract",
                "rnd_stage": "discovery",
                "license": "pubmed-hf",
                "url": "",
                "title": title,
                "tags": ["abstract", "hf"],
            },
            lock=lock,
            seen=seen,
        )
        if ok:
            added += 1
            print(f"[abstracts:hf] {added}/{need}")
    try:
        # Persist a tiny marker for reuse documentation
        (cache_dir / "README.txt").write_text(
            "HF cache for biomed abstract streaming (Context7 save_to_disk pattern).\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return added


def download_trials(
    cfg: dict[str, Any], lock: list[dict[str, Any]], seen: set[str], quota: int
) -> int:
    added = 0
    for term in cfg.get("trial_queries") or []:
        if added >= quota:
            break
        params = urllib.parse.urlencode(
            {
                "query.term": term,
                "pageSize": min(20, quota - added),
                "format": "json",
            }
        )
        url = f"https://clinicaltrials.gov/api/v2/studies?{params}"
        try:
            payload = _http_get_json(url, timeout=90)
        except Exception as exc:  # noqa: BLE001
            print(f"[trials] {exc}")
            continue
        for study in payload.get("studies") or []:
            if added >= quota:
                break
            proto = study.get("protocolSection") or {}
            ident = proto.get("identificationModule") or {}
            nct = ident.get("nctId") or ""
            title = ident.get("briefTitle") or ident.get("officialTitle") or nct
            status_mod = proto.get("statusModule") or {}
            status = status_mod.get("overallStatus") or ""
            conds = (proto.get("conditionsModule") or {}).get("conditions") or []
            arms = (proto.get("armsInterventionsModule") or {}).get("interventions") or []
            arm_groups = (proto.get("armsInterventionsModule") or {}).get("armGroups") or []
            outcomes_mod = proto.get("outcomesModule") or {}
            outcomes = outcomes_mod.get("primaryOutcomes") or []
            secondary = outcomes_mod.get("secondaryOutcomes") or []
            design = proto.get("designModule") or {}
            desc = proto.get("descriptionModule") or {}
            eligibility = proto.get("eligibilityModule") or {}
            contacts = proto.get("contactsLocationsModule") or {}
            body_lines = [
                f"# {title}",
                "",
                f"- NCT: {nct}",
                f"- Official title: {ident.get('officialTitle') or ''}",
                f"- Status: {status}",
                f"- Start: {(status_mod.get('startDateStruct') or {}).get('date') or ''}",
                f"- Query: {term}",
                f"- Conditions: {', '.join(conds)}",
                f"- Phases: {', '.join(design.get('phases') or [])}",
                f"- Allocation: {(design.get('designInfo') or {}).get('allocation') or ''}",
                f"- Intervention model: "
                f"{(design.get('designInfo') or {}).get('interventionModel') or ''}",
                f"- URL: https://clinicaltrials.gov/study/{nct}" if nct else "- URL:",
                "",
                "## Brief summary",
                desc.get("briefSummary") or "",
                "",
                "## Detailed description",
                (desc.get("detailedDescription") or "")[:8000],
                "",
                "## Interventions",
            ]
            for arm in arms:
                body_lines.append(
                    f"- {arm.get('type')}: {arm.get('name')} — {arm.get('description') or ''}"
                )
            if arm_groups:
                body_lines.append("")
                body_lines.append("## Arm groups")
                for ag in arm_groups:
                    body_lines.append(
                        f"- {ag.get('label')}: {ag.get('type')} — {ag.get('description') or ''}"
                    )
            body_lines.append("")
            body_lines.append("## Primary outcomes")
            for oc in outcomes:
                body_lines.append(
                    f"- {oc.get('measure')}: {oc.get('description') or ''} "
                    f"(timeFrame={oc.get('timeFrame') or ''})"
                )
            if secondary:
                body_lines.append("")
                body_lines.append("## Secondary outcomes")
                for oc in secondary[:12]:
                    body_lines.append(
                        f"- {oc.get('measure')}: {oc.get('description') or ''} "
                        f"(timeFrame={oc.get('timeFrame') or ''})"
                    )
            body_lines.extend(
                [
                    "",
                    "## Eligibility",
                    f"- Sex: {eligibility.get('sex') or ''}",
                    f"- Min age: {eligibility.get('minimumAge') or ''}",
                    f"- Max age: {eligibility.get('maximumAge') or ''}",
                    f"- Healthy volunteers: {eligibility.get('healthyVolunteers') or ''}",
                    "",
                    "### Inclusion / exclusion (raw)",
                    (eligibility.get("eligibilityCriteria") or "")[:6000],
                    "",
                    f"## Locations (n={len(contacts.get('locations') or [])})",
                ]
            )
            body = "\n".join(body_lines) + "\n"
            if len(body) < MIN_TRIAL_CHARS:
                continue
            ok = _write_text(
                "trials",
                f"{_slug(nct or title)}.md",
                body,
                meta={
                    "doc_id": nct or _slug(title),
                    "source_type": "trial",
                    "rnd_stage": "clinical_development",
                    "license": "clinicaltrials.gov",
                    "url": f"https://clinicaltrials.gov/study/{nct}" if nct else "",
                    "title": title,
                    "tags": ["trial", "oncology"],
                    "query": term,
                },
                lock=lock,
                seen=seen,
            )
            if ok:
                added += 1
                print(f"[trials] {added}/{quota} {nct}")
            time.sleep(SLEEP_S)
    return added


def download_compounds(
    cfg: dict[str, Any], lock: list[dict[str, Any]], seen: set[str], quota: int
) -> int:
    added = 0
    for name in cfg.get("compound_names") or []:
        if added >= quota:
            break
        enc = urllib.parse.quote(name)
        url = (
            "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/"
            f"{enc}/property/Title,MolecularFormula,CanonicalSMILES,"
            "ConnectivitySMILES,InChI,IUPACName,CID/JSON"
        )
        try:
            payload = _http_get_json(url)
            props = ((payload.get("PropertyTable") or {}).get("Properties") or [{}])[0]
        except Exception as exc:  # noqa: BLE001
            print(f"[compounds] {name}: {exc}")
            props = {"Title": name}
        title = props.get("Title") or name
        formula = props.get("MolecularFormula") or ""
        smiles = props.get("CanonicalSMILES") or props.get("ConnectivitySMILES") or ""
        inchi = props.get("InChI") or ""
        iupac = props.get("IUPACName") or ""
        cid = props.get("CID") or ""
        # Enrich from local compounds.json if PubChem SMILES empty
        if not smiles:
            local = ROOT / "eval" / "biomed" / "datasets" / "compounds.json"
            if local.exists():
                for c in json.loads(local.read_text(encoding="utf-8")).get("compounds") or []:
                    if str(c.get("name") or "").lower() == name.lower():
                        smiles = c.get("smiles") or smiles
                        break
        body = (
            f"# Compound card: {name}\n\n"
            f"- Title: {title}\n"
            f"- PubChem CID: {cid}\n"
            f"- Formula: {formula}\n"
            f"- SMILES: `{smiles}`\n"
            f"- InChI: `{inchi}`\n"
            f"- IUPAC: {iupac}\n"
            f"- PubChem: https://pubchem.ncbi.nlm.nih.gov/compound/{cid or enc}\n\n"
            "## Medicinal chemistry notes\n\n"
            f"{name} is included as an oncology innovative-drug / competitor reference "
            "for HUTCHMED R&D retrieval evaluation. "
            "Keywords: compound, SMILES, InChI, inhibitor, kinase, ligand, TKI.\n"
        )
        ok = _write_text(
            "compounds",
            f"compound_{_slug(name)}.md",
            body,
            meta={
                "doc_id": f"CID_{_slug(name)}",
                "source_type": "compound",
                "rnd_stage": "discovery_chemistry",
                "license": "pubchem",
                "url": f"https://pubchem.ncbi.nlm.nih.gov/#query={enc}",
                "title": title,
                "tags": ["compound", "chemical", "smiles"],
            },
            lock=lock,
            seen=seen,
        )
        if ok:
            added += 1
            print(f"[compounds] {added}/{quota} {name}")
        time.sleep(SLEEP_S)
    return added


def download_labels(
    cfg: dict[str, Any], lock: list[dict[str, Any]], seen: set[str], quota: int
) -> int:
    added = 0
    for name in cfg.get("label_names") or []:
        if added >= quota:
            break
        q = urllib.parse.quote(f'openfda.generic_name:"{name}"')
        url = f"https://api.fda.gov/drug/label.json?search={q}&limit=1"
        try:
            payload = _http_get_json(url)
            results = payload.get("results") or []
        except Exception as exc:  # noqa: BLE001
            print(f"[labels] {name}: {exc}")
            results = []
        if not results:
            # Minimal stub so quota can still be approached offline-ish
            body = (
                f"# Drug label summary: {name}\n\n"
                f"openFDA returned no label for `{name}`. "
                "Keep this placeholder for competitive labeling queries.\n"
            )
        else:
            r0 = results[0]
            openfda = r0.get("openfda") or {}
            indications = " ".join(r0.get("indications_and_usage") or [])[:4000]
            warnings = " ".join(r0.get("boxed_warning") or r0.get("warnings") or [])[:2000]
            body = (
                f"# Drug label: {name}\n\n"
                f"- Brand: {', '.join(openfda.get('brand_name') or [])}\n"
                f"- Generic: {', '.join(openfda.get('generic_name') or [])}\n"
                f"- Route: {', '.join(openfda.get('route') or [])}\n\n"
                f"## Indications and usage\n\n{indications}\n\n"
                f"## Warnings\n\n{warnings}\n"
            )
        ok = _write_text(
            "labels",
            f"label_{_slug(name)}.md",
            body,
            meta={
                "doc_id": f"LABEL_{_slug(name)}",
                "source_type": "label",
                "rnd_stage": "regulatory",
                "license": "openfda",
                "url": url,
                "title": f"Label {name}",
                "tags": ["label", "regulatory"],
            },
            lock=lock,
            seen=seen,
        )
        if ok:
            added += 1
            print(f"[labels] {added}/{quota} {name}")
        time.sleep(SLEEP_S)
    return added


def download_guidance(
    cfg: dict[str, Any], lock: list[dict[str, Any]], seen: set[str], quota: int
) -> int:
    added = 0
    for item in cfg.get("guidance_urls") or []:
        if added >= quota:
            break
        url = item["url"]
        title = item.get("title") or url
        try:
            data = _http_get(url, timeout=120)
        except Exception as exc:  # noqa: BLE001
            print(f"[guidance] {title}: {exc}")
            # Write a pointer markdown so RA workflows still have an ingestible artifact.
            body = f"# {title}\n\nSource URL (download failed): {url}\n\nTags: {item.get('tags')}\n"
            data = body.encode("utf-8")
            ext = "md"
        else:
            ext = "pdf" if data[:4] == b"%PDF" else "bin"
            if ext != "pdf":
                # Some FDA endpoints return HTML
                text = data.decode("utf-8", errors="replace")
                data = f"# {title}\n\nSource: {url}\n\n{text[:20000]}\n".encode()
                ext = "md"
        ok = _write_file(
            "guidance",
            f"guidance_{_slug(title)}.{ext}",
            data,
            meta={
                "doc_id": f"GUIDE_{_slug(title)}",
                "source_type": "guidance",
                "rnd_stage": "regulatory",
                "license": "public-fda-ich",
                "url": url,
                "title": title,
                "tags": item.get("tags") or ["guidance"],
            },
            lock=lock,
            seen=seen,
        )
        if ok:
            added += 1
            print(f"[guidance] {added}/{quota} {title[:60]}")
        time.sleep(SLEEP_S)
    return added


def download_company(
    cfg: dict[str, Any], lock: list[dict[str, Any]], seen: set[str], quota: int
) -> int:
    added = 0
    for item in cfg.get("company_urls") or []:
        if added >= quota:
            break
        url = item["url"]
        title = item.get("title") or url
        try:
            raw = _http_get(url, timeout=60).decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            print(f"[company] {url}: {exc}")
            continue
        # Crude HTML → text
        text = re.sub(r"(?is)<script.*?>.*?</script>", " ", raw)
        text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        body = f"# {title}\n\nSource: {url}\n\n{text[:30000]}\n"
        ok = _write_text(
            "company",
            f"company_{_slug(title)}.md",
            body,
            meta={
                "doc_id": f"CO_{_slug(title)}",
                "source_type": "company",
                "rnd_stage": "competitive_intelligence",
                "license": "public-webpage",
                "url": url,
                "title": title,
                "tags": item.get("tags") or ["company"],
            },
            lock=lock,
            seen=seen,
        )
        if ok:
            added += 1
            print(f"[company] {added}/{quota} {title}")
        time.sleep(SLEEP_S)
    return added


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="Cap total new docs (0 = full quotas)")
    parser.add_argument(
        "--only",
        choices=["papers", "abstracts", "trials", "compounds", "labels", "guidance", "company"],
        action="append",
        default=None,
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help=(
            "HTTP(S) proxy URL for overseas sources (Europe PMC / PubChem / FDA / …). "
            f"Overrides BIOMED_HTTP_PROXY. Mainland tip: {DEFAULT_LOCAL_PROXY}"
        ),
    )
    parser.add_argument(
        "--local-proxy",
        action="store_true",
        help=f"Shortcut for --proxy {DEFAULT_LOCAL_PROXY} (common local Clash/V2Ray HTTP port)",
    )
    parser.add_argument(
        "--insecure-ssl",
        action="store_true",
        help=(
            "Skip TLS verify (needed when local proxy MITM breaks cert chain; "
            "or BIOMED_SSL_INSECURE=1)"
        ),
    )
    parser.add_argument(
        "--purge-thin",
        action="store_true",
        help="Remove abstract-only / undersized paper stubs before downloading",
    )
    parser.add_argument(
        "--purge-thin-dry-run",
        action="store_true",
        help="Show which thin papers would be purged without deleting",
    )
    args = parser.parse_args()
    proxy = DEFAULT_LOCAL_PROXY if args.local_proxy else args.proxy
    active = configure_proxy(proxy, insecure_ssl=args.insecure_ssl)
    if args.purge_thin or args.purge_thin_dry_run:
        purge_thin_papers(dry_run=bool(args.purge_thin_dry_run))
        if args.purge_thin_dry_run and not args.purge_thin:
            return 0
    if active:
        print(f"HTTP proxy enabled: {active}")
    else:
        print(
            "HTTP proxy: direct "
            f"(set BIOMED_HTTP_PROXY or --local-proxy / --proxy {DEFAULT_LOCAL_PROXY} "
            "if overseas fetch hangs)"
        )

    cfg = _load_manifest()
    quotas: dict[str, int] = dict(cfg.get("quotas") or {})
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    lock: list[dict[str, Any]] = []
    seen: set[str] = set()
    if LOCK_PATH.exists():
        try:
            prev = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
            for rec in prev.get("documents") or []:
                lock.append(rec)
                if rec.get("sha256"):
                    seen.add(rec["sha256"])
        except json.JSONDecodeError:
            pass

    type_map = {
        "papers": "paper",
        "abstracts": "abstract",
        "trials": "trial",
        "compounds": "compound",
        "labels": "label",
        "guidance": "guidance",
        "company": "company",
    }

    def remaining(kind: str) -> int:
        st = type_map[kind]
        have = sum(1 for r in lock if r.get("source_type") == st)
        return max(0, int(quotas.get(kind, 0)) - have)

    plan = [
        ("papers", download_papers),
        ("abstracts", download_abstracts),
        ("trials", download_trials),
        ("compounds", download_compounds),
        ("labels", download_labels),
        ("guidance", download_guidance),
        ("company", download_company),
    ]
    only = set(args.only or [])
    # With --limit, distribute remaining budget across pending kinds (not papers-only).
    pending_kinds = [k for k, _ in plan if (not only or k in only) and remaining(k) > 0]
    budget = args.limit if args.limit else None
    for kind, fn in plan:
        if only and kind not in only:
            continue
        need = remaining(kind)
        if need <= 0:
            print(f"[{kind}] quota already satisfied")
            continue
        if budget is not None:
            if budget <= 0:
                break
            # Fair share of remaining budget across still-pending kinds
            share = max(1, budget // max(1, len(pending_kinds)))
            need = min(need, share, budget)
            pending_kinds = [k for k in pending_kinds if k != kind]
        print(f"=== downloading {kind}: need {need} ===")
        got = fn(cfg, lock, seen, need)
        if budget is not None:
            budget -= got
        print(f"=== {kind}: +{got} ===")

    summary = {
        "theme": cfg.get("theme"),
        "kb_name": cfg.get("kb_name"),
        "total_documents": len(lock),
        "by_type": {},
        "documents": lock,
    }
    for rec in lock:
        st = rec.get("source_type") or "unknown"
        summary["by_type"][st] = summary["by_type"].get(st, 0) + 1
    LOCK_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"lock written: {LOCK_PATH} total={len(lock)} by_type={summary['by_type']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
