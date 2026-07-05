"""Section summary indexing and parent-document retrieval tests (Plan A + B).

Covers:
- ``chunks_to_text_nodes``: ``document_top_summary`` is written to metadata as a scalar field (Plan
A).
- ``sections_to_text_nodes``: recursively flattens the ``doc_nav.sections`` tree, skipping sections
  with empty summary / chunk_count==0, producing TextNodes with ``type="section_summary"`` (Plan B).
- Two-stage retrieval simulation: first recall sections by ``type=section_summary``, then drill down
  to fine-grained chunks via ``path`` prefix (parent-child linkage).
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from eagle_rag.ingest.knowhere_adapter import (
    chunks_to_text_nodes,
    sections_to_text_nodes,
)

# ---------------------------------------------------------------------------
# Helpers: build chunk / doc_nav
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id,
    *,
    type="text",
    content="",
    path="",
    summary="",
    document_top_summary="",
    file_path="",
    html=None,
    data=None,
) -> SimpleNamespace:
    """Build a Knowhere SDK chunk duck-typed object (with nested metadata, matching the real SDK
    shape)."""
    return SimpleNamespace(
        chunk_id=chunk_id,
        type=type,
        content=content,
        path=path,
        html=html,
        data=data,
        metadata=SimpleNamespace(
            summary=summary,
            keywords=[],
            page_nums=[],
            connect_to=[],
            file_path=file_path,
            document_top_summary=document_top_summary,
            original_name=None,
            table_type=None,
        ),
    )


def _make_section(title, path, level, summary, chunk_count, children=None) -> SimpleNamespace:
    """Build a doc_nav section object (matching the SDK ``DocNavSection`` shape)."""
    return SimpleNamespace(
        title=title,
        path=path,
        level=level,
        summary=summary,
        chunk_count=chunk_count,
        children=children or [],
    )


def _make_parse_result(chunks, sections=None) -> SimpleNamespace:
    """Build a ParseResult duck-typed object; mounts doc_nav when sections is not None."""
    pr = SimpleNamespace(
        chunks=chunks,
        text_chunks=[c for c in chunks if c.type == "text"],
        image_chunks=[c for c in chunks if c.type == "image"],
        table_chunks=[c for c in chunks if c.type == "table"],
        manifest=SimpleNamespace(source_file_name="doc.pdf", job_id=None),
        full_markdown="",
        document_id=None,
        namespace=None,
    )
    if sections is not None:
        pr.doc_nav = SimpleNamespace(sections=sections, resources=None)
    return pr


# ---------------------------------------------------------------------------
# Plan A: document_top_summary goes into metadata
# ---------------------------------------------------------------------------


def test_document_top_summary_in_metadata():
    """Plan A: a chunk's document_top_summary is written to node.metadata as a scalar field."""
    top = "This document includes: Abstract, 1 Introduction, 3 Model Architecture"
    chunk = _make_chunk("c1", content="正文", path="doc.pdf/Abstract", document_top_summary=top)
    pr = _make_parse_result([chunk])

    nodes = chunks_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")

    assert len(nodes) == 1
    assert nodes[0].metadata["document_top_summary"] == top
    assert nodes[0].ref_doc_id == "doc-1"


def test_chunks_and_sections_set_ref_doc_id_for_milvus_doc_id():
    """SOURCE relationship populates Milvus ``doc_id`` on insert."""
    chunk = _make_chunk("c1", content="正文", path="doc.pdf/Abstract")
    pr = _make_parse_result([chunk])
    chunk_nodes = chunks_to_text_nodes(
        pr, document_id="doc-uuid", source_type="policy", kb_name="kb"
    )
    assert chunk_nodes[0].ref_doc_id == "doc-uuid"

    sections = [_make_section("Intro", "doc.pdf/Intro", 1, "intro summary", 2)]
    pr2 = _make_parse_result([], sections=sections)
    sec_nodes = sections_to_text_nodes(
        pr2, document_id="doc-uuid", source_type="policy", kb_name="kb"
    )
    assert len(sec_nodes) == 1
    assert sec_nodes[0].ref_doc_id == "doc-uuid"


def test_document_top_summary_default_empty():
    """When metadata has no document_top_summary, it falls back to an empty string without error."""
    chunk = _make_chunk("c1", content="正文")
    pr = _make_parse_result([chunk])

    nodes = chunks_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")

    assert nodes[0].metadata["document_top_summary"] == ""


# ---------------------------------------------------------------------------
# Plan B: sections_to_text_nodes flattens doc_nav
# ---------------------------------------------------------------------------


def test_sections_flatten_tree():
    """Recursively flattens the doc_nav.sections tree, including nested children."""
    sections = [
        _make_section(
            "Root",
            "doc.pdf",
            1,
            "文档根摘要",
            35,
            [
                _make_section("Abstract", "doc.pdf/Abstract", 1, "摘要内容", 2, []),
                _make_section(
                    "3 Model Architecture",
                    "doc.pdf/3 Model Architecture",
                    1,
                    "架构总览",
                    5,
                    [
                        _make_section(
                            "3.2 Attention",
                            "doc.pdf/3 Model Architecture/3.2 Attention",
                            2,
                            "注意力机制",
                            3,
                            [],
                        ),
                    ],
                ),
            ],
        ),
    ]
    pr = _make_parse_result([], sections=sections)

    nodes = sections_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")

    # 4 non-empty sections (Root/Abstract/3 Model Architecture/3.2 Attention).
    assert len(nodes) == 4
    paths = [n.metadata["path"] for n in nodes]
    assert "doc.pdf" in paths
    assert "doc.pdf/3 Model Architecture/3.2 Attention" in paths


def test_sections_skip_empty_summary():
    """Sections with empty or whitespace-only summary are skipped."""
    sections = [
        _make_section("有摘要", "doc.pdf/s1", 1, "内容", 3, []),
        _make_section("无摘要", "doc.pdf/s2", 1, "", 3, []),
        _make_section("仅空白", "doc.pdf/s3", 1, "   ", 3, []),
    ]
    pr = _make_parse_result([], sections=sections)

    nodes = sections_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")

    assert len(nodes) == 1
    assert nodes[0].metadata["path"] == "doc.pdf/s1"


def test_sections_skip_zero_chunk_count():
    """Sections with chunk_count==0 are skipped (leaf nodes with no content only add noise)."""
    sections = [
        _make_section("有 chunk", "doc.pdf/s1", 1, "内容", 3, []),
        _make_section("无 chunk", "doc.pdf/s2", 1, "内容", 0, []),
    ]
    pr = _make_parse_result([], sections=sections)

    nodes = sections_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")

    assert len(nodes) == 1
    assert nodes[0].metadata["path"] == "doc.pdf/s1"


def test_sections_no_doc_nav():
    """When parse_result has no doc_nav attribute, returns [] (legacy SDK compatibility)."""
    pr = SimpleNamespace(chunks=[])  # no doc_nav attribute

    nodes = sections_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")

    assert nodes == []


def test_sections_doc_nav_none():
    """When parse_result.doc_nav is None, returns an empty list."""
    pr = SimpleNamespace(chunks=[], doc_nav=None)

    nodes = sections_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")

    assert nodes == []


def test_sections_id_stable():
    """The same document_id + path produces the same id_ (idempotent upsert)."""
    sections = [_make_section("S", "doc.pdf/s1", 1, "内容", 3, [])]
    pr1 = _make_parse_result([], sections=sections)
    pr2 = _make_parse_result([], sections=sections)

    nodes1 = sections_to_text_nodes(pr1, document_id="doc-1", source_type="policy", kb_name="kb")
    nodes2 = sections_to_text_nodes(pr2, document_id="doc-1", source_type="policy", kb_name="kb")

    assert nodes1[0].id_ == nodes2[0].id_
    # id format: sec_ + first 16 chars of sha1.
    expected = "sec_" + hashlib.sha1(b"doc-1:doc.pdf/s1").hexdigest()[:16]
    assert nodes1[0].id_ == expected


def test_sections_id_different_per_document():
    """Different document_ids produce different id_s (avoids cross-document collisions)."""
    sections = [_make_section("S", "doc.pdf/s1", 1, "内容", 3, [])]
    pr = _make_parse_result([], sections=sections)

    nodes_a = sections_to_text_nodes(pr, document_id="doc-A", source_type="policy", kb_name="kb")
    nodes_b = sections_to_text_nodes(pr, document_id="doc-B", source_type="policy", kb_name="kb")

    assert nodes_a[0].id_ != nodes_b[0].id_


def test_sections_metadata_fields():
    """A section node contains type=section_summary and all associated fields."""
    sections = [
        _make_section(
            "3.2 Attention",
            "doc.pdf/3 Model Architecture/3.2 Attention",
            2,
            "注意力机制摘要",
            3,
            [],
        )
    ]
    pr = _make_parse_result([], sections=sections)

    nodes = sections_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="finance")

    assert len(nodes) == 1
    m = nodes[0].metadata
    assert m["type"] == "section_summary"
    assert m["path"] == "doc.pdf/3 Model Architecture/3.2 Attention"
    assert m["level"] == 2
    assert m["summary"] == "注意力机制摘要"
    assert m["chunk_count"] == 3
    assert m["document_id"] == "doc-1"
    assert m["source_type"] == "policy"
    assert m["kb_name"] == "finance"
    assert nodes[0].text == "注意力机制摘要"


# ---------------------------------------------------------------------------
# Two-stage retrieval simulation: section recall + path prefix drill-down
# ---------------------------------------------------------------------------


def test_two_stage_retrieval_section_then_chunks():
    """Two-stage retrieval: recall sections (type=section_summary), drill down by path prefix.

    Verifies the parent-child linkage in the data structure: a section path is a prefix of its child
    chunk paths, so retrieval can use prefix matching to link parent and child (no extra field
    needed).
    """
    # Section summary (stage 1 recall target).
    section_path = "doc.pdf/3 Model Architecture/3.2 Attention"
    sections = [_make_section("3.2 Attention", section_path, 2, "注意力机制总览", 3, [])]
    pr_sec = _make_parse_result([], sections=sections)
    section_nodes = sections_to_text_nodes(
        pr_sec, document_id="doc-1", source_type="policy", kb_name="kb"
    )

    # Stage 1: filter by type=section_summary (simulates MetadataFilter(key="type")).
    stage1 = [n for n in section_nodes if n.metadata["type"] == "section_summary"]
    assert len(stage1) == 1
    assert stage1[0].metadata["path"] == section_path

    # Fine-grained chunks (stage 2 drill-down targets).
    chunks = [
        _make_chunk(
            "c1",
            content="Scaled Dot-Product Attention",
            path=f"{section_path}/3.2.1 Scaled Dot-Product",
        ),
        _make_chunk(
            "c2",
            content="Multi-Head Attention",
            path=f"{section_path}/3.2.2 Multi-Head Attention",
        ),
        _make_chunk(
            "c3",
            content="无关 chunk",
            path="doc.pdf/5 Training/5.1 Data",
        ),
    ]
    pr_chunk = _make_parse_result(chunks)
    chunk_nodes = chunks_to_text_nodes(
        pr_chunk, document_id="doc-1", source_type="policy", kb_name="kb"
    )

    # Stage 2: filter by section path prefix to drill down.
    stage2 = [n for n in chunk_nodes if n.metadata["path"].startswith(section_path)]
    assert len(stage2) == 2
    assert all(section_path in n.metadata["path"] for n in stage2)
    # Unrelated chunks should not be recalled.
    assert not any("5.1 Data" in n.metadata["path"] for n in stage2)


def test_combined_indexing_chunk_plus_section():
    """knowhere_parse indexed nodes = chunk nodes + section nodes (merged upsert).

    Verifies that both node types coexist in the same collection, distinguished by the type field.
    """
    # chunks
    chunks = [
        _make_chunk("c1", content="正文1", path="doc.pdf/s1"),
        _make_chunk("c2", content="正文2", path="doc.pdf/s2"),
    ]
    pr = _make_parse_result(
        chunks,
        sections=[_make_section("S1", "doc.pdf/s1", 1, "章节摘要1", 2, [])],
    )

    chunk_nodes = chunks_to_text_nodes(pr, document_id="doc-1", source_type="policy", kb_name="kb")
    section_nodes = sections_to_text_nodes(
        pr, document_id="doc-1", source_type="policy", kb_name="kb"
    )
    all_nodes = chunk_nodes + section_nodes

    assert len(all_nodes) == 3
    types = [n.metadata["type"] for n in all_nodes]
    assert types.count("text") == 2
    assert types.count("section_summary") == 1
    # chunk and section share a path prefix (parent-child linkage holds).
    sec_paths = [n.metadata["path"] for n in all_nodes if n.metadata["type"] == "section_summary"]
    chunk_paths = [n.metadata["path"] for n in all_nodes if n.metadata["type"] == "text"]
    assert any(cp.startswith(sec_paths[0]) for cp in chunk_paths)
