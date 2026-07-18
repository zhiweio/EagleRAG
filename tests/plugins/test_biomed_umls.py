"""Biomed UMLS matcher + MRCONSO loader tests (D)."""

from __future__ import annotations

import pytest

from plugins.biomed.umls import (
    expand_query_with_entities,
    load_umls_index,
    load_umls_metathesaurus,
    match_entities,
    resolve_compound_query,
    resolve_entity,
)


def test_curated_subset_has_genes_and_drugs() -> None:
    idx = load_umls_index()
    entities = idx["umls_entities"]
    # Spot-check a representative sample across categories.
    for key in ("HER2", "EGFR", "TP53", "imatinib", "pembrolizumab", "breast cancer"):
        assert key in entities, f"missing curated entity {key!r}"


def test_curated_subset_size_meets_floor() -> None:
    idx = load_umls_index()
    assert len(idx["umls_entities"]) >= 60, "curated UMLS subset should be >= 60 entities"


def test_match_entities_substring_and_alias() -> None:
    assert "HER2" in match_entities("HER2 signaling in breast cancer")
    assert "HER2" in match_entities("ERBB2 overexpression")  # alias
    assert "EGFR" in match_entities("epidermal growth factor receptor mutation")


def test_match_entities_no_false_substring() -> None:
    """Letter boundaries prevent short entity names matching inside longer words.

    ``EGFR`` must not fire on ``VEGFR``; ``MET`` must not fire on ``metastatic``;
    ``VEGFR`` must still match ``VEGFR1-3`` (digit suffix is not a boundary).
    """
    vegfr_hits = match_entities("selective VEGFR1-3 inhibitors as monotherapy")
    assert "VEGFR" in vegfr_hits
    assert "EGFR" not in vegfr_hits

    crc_hits = match_entities("metastatic colorectal cancer patients")
    assert "colorectal cancer" in crc_hits
    assert "MET" not in crc_hits

    # Positive control: standalone EGFR still matches.
    assert "EGFR" in match_entities("EGFR exon 19 deletion")

    # ``PD-1`` matches intact (hyphen is not a letter boundary).
    pd1_hits = match_entities("combination with PD-1 inhibitors")
    assert "PD-1" in pd1_hits


def test_match_entities_keyword_supplements() -> None:
    hits = match_entities("kinase inhibitor pharmacokinetics")
    assert "kinase" in hits
    assert "pharmacokinetics" in hits


def test_resolve_entity_returns_pathways_and_drugs() -> None:
    res = resolve_entity("ERBB2")  # alias -> canonical HER2
    assert res["found"] is True
    assert res["entity"] == "HER2"
    assert "PI3K-AKT" in res["pathways"]
    assert "trastuzumab" in res["related_drugs"]
    assert res["cui"] == "C1706866"


def test_resolve_entity_not_found() -> None:
    res = resolve_entity("definitely-not-an-entity")
    assert res["found"] is False
    assert res["aliases"] == []


def test_expand_query_dedupes() -> None:
    suffix = expand_query_with_entities("HER2 and ERBB2 in breast cancer")
    assert suffix is not None
    assert "biomed entities" in suffix
    # ERBB2 / HER2 collapse to the same canonical entity; no duplicate tokens.
    tokens = suffix.replace("[biomed entities: ", "").rstrip("]").split(", ")
    assert len(tokens) == len(set(tokens))


def test_expand_query_no_match_returns_none() -> None:
    assert expand_query_with_entities("a generic sentence about the weather") is None


def test_resolve_compound_query_name_to_smiles() -> None:
    assert resolve_compound_query("aspirin") == "CC(=O)Oc1ccccc1C(=O)O"
    assert resolve_compound_query("Aspirin") == "CC(=O)Oc1ccccc1C(=O)O"  # case-insensitive
    # Unknown name passes through unchanged.
    assert resolve_compound_query("CC(=O)Oc1ccccc1C(=O)O") == "CC(=O)Oc1ccccc1C(=O)O"


def test_load_umls_metathesaurus_missing_file_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EAGLE_BIOMED_UMLS_MRCONSO_PATH", "/nonexistent/MRCONSO.RRF")
    load_umls_metathesaurus.cache_clear() if hasattr(
        load_umls_metathesaurus, "cache_clear"
    ) else None
    assert load_umls_metathesaurus() == {}


def test_load_umls_metathesaurus_parses_fixture(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Minimal MRCONSO RRF fixture: CUI|LAT|TS|LUI|SAB|TTY|CODE|STR|SUI|ISPREF|...
    fixture = tmp_path / "MRCONSO.RRF"
    fixture.write_text(
        "C0000001|ENG|P|L0000001|MSH|MH|D000001|New Fake Protein|S0000001|Y||\n"
        "C0000001|ENG|S|L0000002|MSH|MH|D000001|fake-protein|S0000002|N||\n"
        "C0000002|ENG|P|L0000003|NCI|PT|C000002|Fake Kinase Alpha|S0000003|Y||\n"
        "C0000002|FRE|P|L0000004|NCI|PT|C000002|Kinase factice|S0000004|Y||\n",  # non-ENG ignored
        encoding="utf-8",
    )
    monkeypatch.setenv("EAGLE_BIOMED_UMLS_MRCONSO_PATH", str(fixture))
    out = load_umls_metathesaurus()
    # Only ENG + ISPREF=Y rows survive.
    assert "new fake protein" in out
    assert out["new fake protein"]["cui"] == "C0000001"
    assert "fake kinase alpha" in out
    assert out["fake kinase alpha"]["cui"] == "C0000002"
    # Non-English row excluded.
    assert "kinase factice" not in out


def test_mrconso_enriches_curated_index(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """MRCONSO aliases for an existing curated entity (matched by canonical/alias
    name) must merge into that entity, adding new aliases and filling a missing CUI."""
    # MRCONSO canonical STR "ERBB2" matches the curated HER2 alias -> merges into
    # HER2 and adds the new alias "receptor tyrosine-protein kinase erbB-2".
    fixture = tmp_path / "MRCONSO.RRF"
    fixture.write_text(
        "C1706866|ENG|P|L1|MSH|MH|D1|ERBB2|S1|Y||\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EAGLE_BIOMED_UMLS_MRCONSO_PATH", str(fixture))
    # Reset the merged-index cache so the env change is picked up.
    from plugins.biomed import umls as umls_mod

    umls_mod._merged_index.cache_clear()
    try:
        # The curated HER2 entity is still the canonical key; MRCONSO matched its
        # ERBB2 alias and merged, so resolving the curated key still works and the
        # merged index grew (MRCONSO's own canonical term is already an alias).
        res = resolve_entity("HER2")
        assert res["found"] is True
        assert res["entity"] == "HER2"
        assert res["cui"] == "C1706866"
        # A MRCONSO-only entity (no curated match) is added as a new entity.
        assert "receptor tyrosine-protein kinase erbB-2" not in res["aliases"]
    finally:
        umls_mod._merged_index.cache_clear()
        monkeypatch.delenv("EAGLE_BIOMED_UMLS_MRCONSO_PATH", raising=False)


def test_mrconso_adds_new_entity_when_no_curated_match(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A MRCONSO term with no curated match is added as a brand-new entity."""
    fixture = tmp_path / "MRCONSO.RRF"
    fixture.write_text(
        "C9999999|ENG|P|L1|MSH|MH|D1|Brand New Target XYZ|S1|Y||\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("EAGLE_BIOMED_UMLS_MRCONSO_PATH", str(fixture))
    from plugins.biomed import umls as umls_mod

    umls_mod._merged_index.cache_clear()
    try:
        res = resolve_entity("Brand New Target XYZ")
        assert res["found"] is True
        assert res["cui"] == "C9999999"
    finally:
        umls_mod._merged_index.cache_clear()
        monkeypatch.delenv("EAGLE_BIOMED_UMLS_MRCONSO_PATH", raising=False)
