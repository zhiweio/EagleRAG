#!/usr/bin/env python3
"""Generate corpus-aligned eval_queries.jsonl and smoke subset for HUTCHMED biomed RAG."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
OUT_DIR = SCRIPTS.parent / "datasets"

sys.path.insert(0, str(SCRIPTS))

from corpus_index import (  # noqa: E402
    build_drug_index,
    expected_for_workflow,
    match_corpus_files,
    route_hint_for_row,
    scan_corpus,
)

# Seed templates (manually curated); expanded rows are corpus-filtered below.
TEMPLATES: list[dict] = [
    {
        "workflow": "literature_review",
        "role": "discovery",
        "query": "fruquintinib VEGFR selective inhibitor mechanism of action",
        "must_include_terms": ["fruquintinib", "VEGFR"],
        "expected_doc_name_substrings": ["fruquintinib"],
        "route_hint": {"collections": ["eagle_text_biomed"], "umls": ["VEGFR", "fruquintinib"]},
    },
    {
        "workflow": "literature_review",
        "role": "discovery",
        "query": "savolitinib MET tyrosine kinase inhibitor NSCLC",
        "must_include_terms": ["savolitinib", "MET"],
        "expected_doc_name_substrings": ["savolitinib"],
        "route_hint": {"collections": ["eagle_text_biomed"], "umls": ["MET", "savolitinib"]},
    },
    {
        "workflow": "literature_review",
        "role": "discovery",
        "query": "surufatinib angio-immuno kinase VEGFR FGFR CSF-1R neuroendocrine",
        "must_include_terms": ["surufatinib"],
        "expected_doc_name_substrings": ["surufatinib"],
        "route_hint": {"umls": ["surufatinib", "VEGFR", "CSF-1R"]},
    },
    {
        "workflow": "literature_review",
        "role": "discovery",
        "query": "MET exon 14 skipping alteration targeted therapy",
        "must_include_terms": ["MET"],
        "expected_doc_name_substrings": ["MET", "savolitinib", "capmatinib"],
        "route_hint": {"umls": ["MET"]},
    },
    {
        "workflow": "literature_review",
        "role": "discovery",
        "query": "angiogenesis VEGFR pathway metastatic colorectal cancer",
        "must_include_terms": ["VEGFR", "colorectal"],
        "expected_doc_name_substrings": ["fruquintinib", "colorectal"],
        "route_hint": {"umls": ["VEGFR", "colorectal cancer"]},
    },
    {
        "workflow": "competitive_intelligence",
        "role": "ci",
        "query": "regorafenib versus fruquintinib metastatic colorectal cancer",
        "must_include_terms": ["regorafenib", "fruquintinib"],
        "expected_doc_name_substrings": ["regorafenib", "fruquintinib"],
        "route_hint": {"umls": ["fruquintinib", "regorafenib"]},
    },
    {
        "workflow": "competitive_intelligence",
        "role": "ci",
        "query": "cabozantinib sunitinib renal cell carcinoma VEGFR TKI landscape",
        "must_include_terms": ["cabozantinib"],
        "expected_doc_name_substrings": ["cabozantinib", "sunitinib"],
        "route_hint": {"umls": ["cabozantinib", "renal cell carcinoma"]},
    },
    {
        "workflow": "competitive_intelligence",
        "role": "ci",
        "query": "lenvatinib FGFR VEGFR competitor profile",
        "must_include_terms": ["lenvatinib"],
        "expected_doc_name_substrings": ["lenvatinib"],
        "route_hint": {"umls": ["lenvatinib", "FGFR"]},
    },
    {
        "workflow": "combination_therapy",
        "role": "clinical",
        "query": "fruquintinib sintilimab renal cell carcinoma combination",
        "must_include_terms": ["fruquintinib", "sintilimab"],
        "expected_doc_name_substrings": ["sintilimab"],
        "route_hint": {"umls": ["fruquintinib", "sintilimab"]},
    },
    {
        "workflow": "combination_therapy",
        "role": "clinical",
        "query": "savolitinib osimertinib EGFR mutant NSCLC MET amplification",
        "must_include_terms": ["savolitinib"],
        "expected_doc_name_substrings": ["savolitinib"],
        "route_hint": {"umls": ["savolitinib", "osimertinib", "EGFR", "MET"]},
    },
    {
        "workflow": "combination_therapy",
        "role": "clinical",
        "query": "surufatinib pancreatic ductal adenocarcinoma phase III",
        "must_include_terms": ["surufatinib", "pancreatic"],
        "expected_doc_name_substrings": ["surufatinib", "pancreatic"],
        "route_hint": {"umls": ["surufatinib", "pancreatic cancer"]},
    },
    {
        "workflow": "clinical_trial",
        "role": "clinical",
        "query": "clinical trial fruquintinib metastatic colorectal cancer primary endpoint",
        "must_include_terms": ["fruquintinib"],
        "expected_doc_name_substrings": ["fruquintinib"],
        "route_hint": {"umls": ["fruquintinib"]},
    },
    {
        "workflow": "clinical_trial",
        "role": "clinical",
        "query": "HMPL-504 savolitinib clinical study status",
        "must_include_terms": ["savolitinib"],
        "expected_doc_name_substrings": ["savolitinib"],
        "route_hint": {"umls": ["savolitinib"]},
    },
    {
        "workflow": "compound_match",
        "role": "medchem",
        "query": "SMILES structure fruquintinib compound kinase inhibitor",
        "must_include_terms": ["fruquintinib"],
        "expected_doc_name_substrings": ["fruquintinib"],
        "route_hint": {"collections": ["eagle_chemical"], "umls": ["fruquintinib"]},
    },
    {
        "workflow": "compound_match",
        "role": "medchem",
        "query": "InChI savolitinib MET inhibitor chemical structure",
        "must_include_terms": ["savolitinib"],
        "expected_doc_name_substrings": ["savolitinib"],
        "route_hint": {"collections": ["eagle_chemical"]},
    },
    {
        "workflow": "compound_match",
        "role": "medchem",
        "query": "compound card surufatinib SMILES ligand inhibitor",
        "must_include_terms": ["surufatinib"],
        "expected_doc_name_substrings": ["surufatinib"],
        "route_hint": {"collections": ["eagle_chemical"]},
    },
    {
        "workflow": "regulatory",
        "role": "ra",
        "query": "FDA clinical trial endpoints for cancer drugs and biologics guidance",
        "must_include_terms": ["endpoint", "cancer"],
        "expected_doc_name_substrings": ["guidance"],
        "route_hint": {},
    },
    {
        "workflow": "regulatory",
        "role": "ra",
        "query": "sunitinib drug label indications and usage renal cell carcinoma",
        "must_include_terms": ["sunitinib"],
        "expected_doc_name_substrings": ["sunitinib"],
        "route_hint": {"umls": ["sunitinib"]},
    },
    {
        "workflow": "regulatory",
        "role": "ra",
        "query": "ICH E6 good clinical practice oncology trial conduct",
        "must_include_terms": ["clinical"],
        "expected_doc_name_substrings": ["guidance", "E6"],
        "route_hint": {},
    },
    {
        "workflow": "pipeline",
        "role": "ci",
        "query": "HUTCHMED pipeline fruquintinib savolitinib surufatinib",
        "must_include_terms": ["HUTCHMED"],
        "expected_doc_name_substrings": ["company", "HUTCHMED"],
        "route_hint": {},
    },
]

EXPAND = [
    ("literature_review", "discovery", "{drug} pharmacokinetics safety adverse events", ["{drug}"]),
    (
        "literature_review",
        "discovery",
        "{drug} progression-free survival overall survival",
        ["{drug}"],
    ),
    ("literature_review", "discovery", "{drug} biomarker patient selection", ["{drug}"]),
    (
        "competitive_intelligence",
        "ci",
        "{drug} differentiation versus standard of care TKI",
        ["{drug}"],
    ),
    ("clinical_trial", "clinical", "{drug} phase 3 randomized controlled trial", ["{drug}"]),
    ("clinical_trial", "clinical", "NCT study {drug} intervention arm outcomes", ["{drug}"]),
    ("compound_match", "medchem", "{drug} molecular formula SMILES compound", ["{drug}"]),
    ("regulatory", "ra", "{drug} prescribing information label warnings", ["{drug}"]),
]

PREFERRED_DRUGS = [
    "fruquintinib",
    "savolitinib",
    "surufatinib",
    "sunitinib",
    "cabozantinib",
    "lenvatinib",
    "regorafenib",
    "osimertinib",
    "gefitinib",
    "bevacizumab",
    "sintilimab",
    "capmatinib",
    "tepotinib",
    "everolimus",
]


def _filter_expected(
    expected: list[str],
    corpus_files: list,
) -> list[str]:
    """Keep only expected substrings that match at least one corpus filename."""
    kept = []
    for sub in expected:
        if match_corpus_files(corpus_files, [sub]):
            kept.append(sub)
    return kept


def main() -> None:
    corpus_files = scan_corpus()
    drug_index = build_drug_index(corpus_files, PREFERRED_DRUGS)
    drugs = [d for d in PREFERRED_DRUGS if d in drug_index]

    rows: list[dict] = []
    for i, t in enumerate(TEMPLATES, start=1):
        expected = _filter_expected(list(t["expected_doc_name_substrings"]), corpus_files)
        if not expected:
            continue
        row = {
            "id": f"q-seed-{i:03d}",
            "k": 5,
            **t,
            "expected_doc_name_substrings": expected,
        }
        hint = dict(t.get("route_hint") or {})
        hint.update(route_hint_for_row(str(t["workflow"]), str(t["query"])))
        row["route_hint"] = hint
        rows.append(row)

    n = len(rows)
    for drug in drugs:
        for workflow, role, stem, terms in EXPAND:
            expected = expected_for_workflow(drug, workflow, drug_index)
            if not expected:
                continue
            n += 1
            q = stem.format(drug=drug)
            must = [t.format(drug=drug) for t in terms]
            hint = route_hint_for_row(workflow, q)
            hint.setdefault("umls", [drug])
            rows.append(
                {
                    "id": f"q-exp-{n:03d}",
                    "workflow": workflow,
                    "role": role,
                    "query": q,
                    "must_include_terms": must,
                    "expected_doc_name_substrings": expected,
                    "route_hint": hint,
                    "k": 5,
                }
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_path = OUT_DIR / "eval_queries.jsonl"
    with full_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    smoke = rows[:30] if len(rows) >= 30 else list(rows)
    smoke_path = OUT_DIR / "eval_queries.smoke.jsonl"
    with smoke_path.open("w", encoding="utf-8") as fh:
        for row in smoke:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"wrote {full_path} ({len(rows)} queries)")
    print(f"wrote {smoke_path} ({len(smoke)} queries)")
    print(f"corpus drugs indexed: {len(drug_index)}")


if __name__ == "__main__":
    main()
