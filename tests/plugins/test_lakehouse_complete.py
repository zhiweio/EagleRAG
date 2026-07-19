"""Lakehouse BI connector + YAML chunking tests."""

from __future__ import annotations

from pathlib import Path

from eagle_rag.plugins.hookbus import HookContext
from plugins.lakehouse_bi.example_connector import (
    FileExportLakehouseConnector,
    export_connector_to_dir,
)
from plugins.lakehouse_bi.ingest_hooks import _yaml_nodes_from_text, lakehouse_chunk_transform


def test_yaml_asset_chunking_splits_top_level_keys() -> None:
    sample = Path("plugins/lakehouse_bi/assets/example_semantic_layer.yaml").read_text(
        encoding="utf-8"
    )
    chunks = _yaml_nodes_from_text(sample, source_path="example.yaml")
    types = {c["metadata"]["type"] for c in chunks}
    assert "metric" in types
    assert "semantic_model" in types
    assert "business_rule" in types
    assert "fewshot" in types


def test_ddl_chunk_extracts_columns() -> None:
    from llama_index.core.schema import TextNode

    ddl = Path("plugins/lakehouse_bi/assets/example_orders.sql").read_text(encoding="utf-8")
    nodes = [TextNode(text=ddl, metadata={})]
    out = lakehouse_chunk_transform(
        HookContext(plugin_namespace="lakehouse-bi"),
        nodes,
        file_path="example_orders.sql",
    )
    assert out[0].metadata["type"] == "table_schema"
    assert out[0].metadata["table_name"] == "orders"
    assert "order_id" in out[0].metadata.get("columns", [])


def test_file_export_connector_roundtrip(tmp_path: Path) -> None:
    src = Path("plugins/lakehouse_bi/assets")
    connector = FileExportLakehouseConnector(src)
    out = export_connector_to_dir(connector, tmp_path / "export")
    assert (out / "ddl").exists()
    assert list((out / "ddl").glob("*.sql"))
