#!/usr/bin/env python3
"""Generate eval_queries.jsonl (>=120) and smoke subset (30) for HUTCHMED biomed RAG."""

from __future__ import annotations

import json
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parents[1] / "datasets"


TEMPLATES: list[dict] = [
    # Discovery / literature
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
        "expected_doc_name_substrings": ["fruquintinib", "VEGFR", "colorectal"],
        "route_hint": {"umls": ["VEGFR", "colorectal cancer"]},
    },
    # Competitive intelligence
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
        "expected_doc_name_substrings": ["cabozantinib", "sunitinib", "RCC"],
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
    # Combinations / clinical
    {
        "workflow": "combination_therapy",
        "role": "clinical",
        "query": "fruquintinib sintilimab renal cell carcinoma combination",
        "must_include_terms": ["fruquintinib", "sintilimab"],
        "expected_doc_name_substrings": ["fruquintinib", "sintilimab"],
        "route_hint": {"umls": ["fruquintinib", "sintilimab"]},
    },
    {
        "workflow": "combination_therapy",
        "role": "clinical",
        "query": "savolitinib osimertinib EGFR mutant NSCLC MET amplification",
        "must_include_terms": ["savolitinib", "osimertinib"],
        "expected_doc_name_substrings": ["savolitinib", "osimertinib"],
        "route_hint": {"umls": ["savolitinib", "osimertinib", "EGFR", "MET"]},
    },
    {
        "workflow": "combination_therapy",
        "role": "clinical",
        "query": "surufatinib camrelizumab pancreatic ductal adenocarcinoma",
        "must_include_terms": ["surufatinib"],
        "expected_doc_name_substrings": ["surufatinib", "camrelizumab", "PDAC", "pancreatic"],
        "route_hint": {"umls": ["surufatinib", "camrelizumab", "pancreatic cancer"]},
    },
    {
        "workflow": "clinical_trial",
        "role": "clinical",
        "query": "clinical trial fruquintinib metastatic colorectal cancer primary endpoint",
        "must_include_terms": ["fruquintinib"],
        "expected_doc_name_substrings": ["fruquintinib", "NCT"],
        "route_hint": {"umls": ["fruquintinib"]},
    },
    {
        "workflow": "clinical_trial",
        "role": "clinical",
        "query": "HMPL-504 savolitinib clinical study status",
        "must_include_terms": ["savolitinib"],
        "expected_doc_name_substrings": ["savolitinib", "HMPL"],
        "route_hint": {"umls": ["savolitinib"]},
    },
    # Chemistry
    {
        "workflow": "compound_match",
        "role": "medchem",
        "query": "SMILES structure fruquintinib compound kinase inhibitor",
        "must_include_terms": ["fruquintinib", "SMILES"],
        "expected_doc_name_substrings": ["compound_fruquintinib", "fruquintinib"],
        "route_hint": {"collections": ["eagle_chemical"], "umls": ["fruquintinib"]},
    },
    {
        "workflow": "compound_match",
        "role": "medchem",
        "query": "InChI savolitinib MET inhibitor chemical structure",
        "must_include_terms": ["savolitinib"],
        "expected_doc_name_substrings": ["compound_savolitinib", "savolitinib"],
        "route_hint": {"collections": ["eagle_chemical"]},
    },
    {
        "workflow": "compound_match",
        "role": "medchem",
        "query": "compound card surufatinib SMILES ligand inhibitor",
        "must_include_terms": ["surufatinib", "SMILES"],
        "expected_doc_name_substrings": ["compound_surufatinib"],
        "route_hint": {"collections": ["eagle_chemical"]},
    },
    # Regulatory
    {
        "workflow": "regulatory",
        "role": "ra",
        "query": "FDA clinical trial endpoints for cancer drugs and biologics guidance",
        "must_include_terms": ["endpoint", "cancer"],
        "expected_doc_name_substrings": ["guidance", "endpoint"],
        "route_hint": {},
    },
    {
        "workflow": "regulatory",
        "role": "ra",
        "query": "sunitinib drug label indications and usage renal cell carcinoma",
        "must_include_terms": ["sunitinib"],
        "expected_doc_name_substrings": ["label_sunitinib", "sunitinib"],
        "route_hint": {"umls": ["sunitinib"]},
    },
    {
        "workflow": "regulatory",
        "role": "ra",
        "query": "ICH E6 good clinical practice oncology trial conduct",
        "must_include_terms": ["clinical"],
        "expected_doc_name_substrings": ["ICH", "guidance", "E6"],
        "route_hint": {},
    },
    # Company / pipeline
    {
        "workflow": "pipeline",
        "role": "ci",
        "query": "HUTCHMED pipeline fruquintinib savolitinib surufatinib",
        "must_include_terms": ["HUTCHMED"],
        "expected_doc_name_substrings": ["pipeline", "HUTCHMED", "company"],
        "route_hint": {},
    },
]

# Extra query stems to expand to >=120
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
    ("compound_match", "medchem", "{drug} molecular formula SMILES compound", ["{drug}", "SMILES"]),
    ("regulatory", "ra", "{drug} prescribing information label warnings", ["{drug}"]),
]

DRUGS = [
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
    "camrelizumab",
    "capmatinib",
    "tepotinib",
    "everolimus",
]


def main() -> None:
    rows: list[dict] = []
    for i, t in enumerate(TEMPLATES, start=1):
        rows.append(
            {
                "id": f"q-seed-{i:03d}",
                "k": 5,
                **t,
            }
        )

    n = len(rows)
    for drug in DRUGS:
        for workflow, role, stem, terms in EXPAND:
            n += 1
            q = stem.format(drug=drug)
            must = [t.format(drug=drug) for t in terms]
            rows.append(
                {
                    "id": f"q-exp-{n:03d}",
                    "workflow": workflow,
                    "role": role,
                    "query": q,
                    "must_include_terms": must,
                    "expected_doc_name_substrings": [drug],
                    "route_hint": {"umls": [drug]},
                    "k": 5,
                }
            )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    full_path = OUT_DIR / "eval_queries.jsonl"
    with full_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Smoke: first of each workflow + pipeline seeds (30)
    smoke: list[dict] = []
    seen_wf: set[str] = set()
    for row in rows:
        wf = row["workflow"]
        if wf not in seen_wf or len(smoke) < 12:
            smoke.append(row)
            seen_wf.add(wf)
        if len(smoke) >= 30:
            break
    # Prefer seed templates first
    smoke = rows[:30]
    smoke_path = OUT_DIR / "eval_queries.smoke.jsonl"
    with smoke_path.open("w", encoding="utf-8") as fh:
        for row in smoke:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"wrote {full_path} ({len(rows)} queries)")
    print(f"wrote {smoke_path} ({len(smoke)} queries)")


if __name__ == "__main__":
    main()
