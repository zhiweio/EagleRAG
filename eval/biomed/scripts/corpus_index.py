"""Corpus indexing and gold-label alignment helpers for biomed eval."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[3]
CORPUS_ROOT = ROOT / "assets" / "biomed" / "hutchmed"

FOLDER_BY_KIND = {
    "compounds": "compounds",
    "labels": "labels",
    "abstracts": "abstracts",
    "trials": "trials",
    "papers": "papers",
    "guidance": "guidance",
    "company": "company",
}

LITERATURE_FOLDERS = frozenset({"abstracts", "trials", "papers"})
REGULATORY_FOLDERS = frozenset({"labels", "guidance"})

AlignmentLabel = Literal["aligned", "partial", "absent"]


@dataclass
class CorpusFile:
    path: Path
    name: str
    folder: str
    drug_hints: list[str] = field(default_factory=list)

    def read_head(self, max_bytes: int = 8192) -> str:
        try:
            return self.path.read_bytes()[:max_bytes].decode("utf-8", errors="replace")
        except OSError:
            return ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def scan_corpus(root: Path | None = None) -> list[CorpusFile]:
    """Walk hutchmed corpus and return file records."""
    base = root or CORPUS_ROOT
    if not base.is_dir():
        return []
    out: list[CorpusFile] = []
    for folder in FOLDER_BY_KIND:
        sub = base / folder
        if not sub.is_dir():
            continue
        for path in sorted(sub.iterdir()):
            if not path.is_file():
                continue
            out.append(
                CorpusFile(
                    path=path,
                    name=path.name,
                    folder=folder,
                )
            )
    return out


def build_drug_index(
    files: list[CorpusFile],
    drugs: list[str],
) -> dict[str, dict[str, list[str]]]:
    """Map preferred drug names to corpus files (filename substring match)."""
    index: dict[str, dict[str, list[str]]] = {}
    for drug in drugs:
        folder_map: dict[str, list[str]] = {}
        needle = drug.lower()
        for cf in files:
            if needle in cf.name.lower():
                folder_map.setdefault(cf.folder, []).append(cf.name)
        if folder_map:
            index[drug] = folder_map
    return index


def match_corpus_files(
    files: list[CorpusFile],
    substrings: list[str],
) -> list[CorpusFile]:
    if not substrings:
        return []
    hits: list[CorpusFile] = []
    for cf in files:
        name_low = cf.name.lower()
        if any(s.lower() in name_low for s in substrings if s):
            hits.append(cf)
    return hits


def terms_in_text(terms: list[str], text: str) -> tuple[bool, list[str]]:
    blob = _norm(text)
    missing = [t for t in terms if _norm(t) not in blob]
    return len(missing) == 0, missing


def workflow_folder_ok(workflow: str, folder: str) -> bool:
    if workflow in {"literature_review", "clinical_trial"}:
        return folder in LITERATURE_FOLDERS
    if workflow == "compound_match":
        return folder == "compounds"
    if workflow == "regulatory":
        return folder in REGULATORY_FOLDERS
    if workflow in {"combination_therapy", "pipeline", "competitive_intelligence"}:
        return folder in LITERATURE_FOLDERS | REGULATORY_FOLDERS | {"company", "compounds"}
    return True


def audit_query_row(
    row: dict[str, Any],
    files: list[CorpusFile] | None = None,
) -> dict[str, Any]:
    """Classify gold-label alignment for one eval query."""
    corpus = files if files is not None else scan_corpus()
    workflow = str(row.get("workflow") or "")
    expected = list(row.get("expected_doc_name_substrings") or [])
    terms = list(row.get("must_include_terms") or [])

    matched = match_corpus_files(corpus, expected)
    if not matched and expected:
        # Fallback: any drug-like token from expected in filename
        for sub in expected:
            matched.extend(
                cf for cf in corpus if sub.lower() in cf.name.lower() and cf not in matched
            )

    filename_ok = len(matched) > 0
    content_ok = False
    workflow_ok = False
    matched_details: list[dict[str, Any]] = []

    for cf in matched:
        head = cf.read_head()
        t_ok, missing = terms_in_text(terms, head) if terms else (True, [])
        w_ok = workflow_folder_ok(workflow, cf.folder)
        matched_details.append(
            {
                "file": cf.name,
                "folder": cf.folder,
                "terms_ok": t_ok,
                "missing_terms": missing,
                "workflow_ok": w_ok,
            }
        )
        content_ok = content_ok or t_ok
        workflow_ok = workflow_ok or w_ok

    if not filename_ok:
        label: AlignmentLabel = "absent"
    elif content_ok and workflow_ok:
        label = "aligned"
    else:
        label = "partial"

    return {
        "id": row.get("id"),
        "workflow": workflow,
        "alignment": label,
        "filename_ok": filename_ok,
        "content_ok": content_ok,
        "workflow_ok": workflow_ok,
        "matched_files": matched_details,
        "expected_doc_name_substrings": expected,
        "must_include_terms": terms,
    }


def expected_for_workflow(
    drug: str,
    workflow: str,
    drug_index: dict[str, dict[str, list[str]]],
) -> list[str] | None:
    """Return expected filename substrings for a drug/workflow, or None to skip."""
    folders = drug_index.get(drug, {})
    if workflow == "compound_match":
        if folders.get("compounds"):
            return [drug]
        return None
    if workflow in {"literature_review", "clinical_trial"}:
        for folder in ("abstracts", "trials", "papers"):
            if folders.get(folder):
                return [drug]
        return None
    if workflow == "regulatory":
        if folders.get("labels"):
            return [f"label_{drug}"]
        if folders.get("guidance"):
            return ["guidance"]
        return None
    if workflow == "competitive_intelligence":
        if any(folders.get(f) for f in folders):
            return [drug]
        return None
    # generic expanded templates
    if any(folders.get(f) for f in folders):
        return [drug]
    return None


def route_hint_for_row(workflow: str, query: str) -> dict[str, Any]:
    hint: dict[str, Any] = {}
    if workflow == "compound_match" or re.search(
        r"\b(SMILES|InChI|compound)\b", query, re.IGNORECASE
    ):
        hint["collections"] = ["eagle_chemical"]
    elif workflow in {"literature_review", "clinical_trial"}:
        hint["collections"] = ["eagle_text_biomed"]
    return hint


def resolve_search_mode(
    row: dict[str, Any],
    *,
    respect_route_hint: bool = True,
) -> str:
    """Pick POST /search mode consistent with route_hint and query text."""
    if not respect_route_hint:
        return "text"
    workflow = str(row.get("workflow") or "")
    query = str(row.get("query") or "")
    route_hint = row.get("route_hint") or {}
    collections = list(route_hint.get("collections") or [])

    if workflow == "compound_match":
        if "eagle_chemical" in collections:
            return "hybrid"
        if re.search(r"\b(SMILES|InChI|compound card)\b", query, re.IGNORECASE):
            return "hybrid"
        return "text"
    if "eagle_chemical" in collections:
        return "hybrid"
    if re.search(r"\b(SMILES|InChI|compound card)\b", query, re.IGNORECASE):
        return "hybrid"
    return "text"
