"""Tests for biomed eval corpus alignment helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "eval" / "biomed" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from corpus_index import (  # noqa: E402
    audit_query_row,
    build_drug_index,
    expected_for_workflow,
    resolve_search_mode,
    scan_corpus,
)
from generate_eval_queries import _filter_expected  # noqa: E402


@pytest.fixture
def mini_corpus(tmp_path: Path) -> Path:
    root = tmp_path / "hutchmed"
    (root / "compounds").mkdir(parents=True)
    (root / "labels").mkdir(parents=True)
    (root / "abstracts").mkdir(parents=True)
    (root / "compounds" / "compound_fruquintinib.md").write_text(
        "# Fruquintinib\nSMILES: CCO\nVEGFR inhibitor\n",
        encoding="utf-8",
    )
    (root / "labels" / "label_sunitinib.md").write_text(
        "# Sunitinib label\nIndications for renal cell carcinoma.\n",
        encoding="utf-8",
    )
    (root / "abstracts" / "abs_fruquintinib_trial.md").write_text(
        "Fruquintinib phase 3 overall survival progression-free survival.\n",
        encoding="utf-8",
    )
    return root


def test_audit_aligned_literature(mini_corpus: Path) -> None:
    files = scan_corpus(mini_corpus)
    row = {
        "id": "t1",
        "workflow": "literature_review",
        "expected_doc_name_substrings": ["fruquintinib"],
        "must_include_terms": ["fruquintinib"],
    }
    result = audit_query_row(row, files)
    assert result["alignment"] == "aligned"


def test_audit_absent_drug(mini_corpus: Path) -> None:
    files = scan_corpus(mini_corpus)
    row = {
        "id": "t2",
        "workflow": "literature_review",
        "expected_doc_name_substrings": ["camrelizumab"],
        "must_include_terms": ["camrelizumab"],
    }
    result = audit_query_row(row, files)
    assert result["alignment"] == "absent"


def test_expected_for_workflow_skips_missing_literature(mini_corpus: Path) -> None:
    files = scan_corpus(mini_corpus)
    drug_index = build_drug_index(files, ["fruquintinib", "savolitinib"])
    assert expected_for_workflow("savolitinib", "literature_review", drug_index) is None
    assert expected_for_workflow("fruquintinib", "compound_match", drug_index) == ["fruquintinib"]


def test_resolve_search_mode_hybrid_for_compound() -> None:
    row = {
        "workflow": "compound_match",
        "query": "fruquintinib SMILES compound",
        "route_hint": {"collections": ["eagle_chemical"]},
    }
    assert resolve_search_mode(row) == "hybrid"


def test_filter_expected_drops_missing(mini_corpus: Path) -> None:
    files = scan_corpus(mini_corpus)
    kept = _filter_expected(["fruquintinib", "camrelizumab"], files)
    assert kept == ["fruquintinib"]
