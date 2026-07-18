"""Example file-based LakehouseMetadataConnector (user-extension template).

EagleRAG never connects to a lakehouse. Users implement a connector that
exports DDL / schema / views to files, then ingest those files via ``/ingest``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from eagle_rag.plugins.contracts.lakehouse import (
    ColumnDescriptor,
    LakehouseMetadataConnector,
    TableDescriptor,
    ViewDescriptor,
)

__all__ = ["FileExportLakehouseConnector", "export_connector_to_dir"]


class FileExportLakehouseConnector(LakehouseMetadataConnector):
    """Reads pre-exported artifacts from a directory (DDL + schema JSON + views)."""

    def __init__(self, export_dir: str | Path) -> None:
        self._root = Path(export_dir)

    def extract_ddl(self) -> Iterator[str]:
        for path in sorted(self._root.glob("**/*.sql")):
            yield path.read_text(encoding="utf-8")
        for path in sorted(self._root.glob("**/*.ddl")):
            yield path.read_text(encoding="utf-8")

    def extract_schema(self) -> list[TableDescriptor]:
        schema_path = self._root / "schema.json"
        if not schema_path.exists():
            return []
        payload = json.loads(schema_path.read_text(encoding="utf-8"))
        tables: list[TableDescriptor] = []
        for item in payload if isinstance(payload, list) else payload.get("tables", []):
            columns = [
                ColumnDescriptor(
                    name=str(col.get("name")),
                    type=str(col.get("type", "STRING")),
                    comment=col.get("comment"),
                    nullable=col.get("nullable"),
                )
                for col in (item.get("columns") or [])
            ]
            tables.append(
                TableDescriptor(
                    table=str(item.get("table") or item.get("name")),
                    columns=columns,
                    database=item.get("database"),
                    schema=item.get("schema"),
                    comment=item.get("comment"),
                )
            )
        return tables

    def extract_views(self) -> list[ViewDescriptor]:
        views_path = self._root / "views.json"
        if not views_path.exists():
            return []
        payload = json.loads(views_path.read_text(encoding="utf-8"))
        out: list[ViewDescriptor] = []
        for item in payload if isinstance(payload, list) else payload.get("views", []):
            out.append(
                ViewDescriptor(
                    name=str(item.get("name")),
                    sql=str(item.get("sql") or ""),
                    database=item.get("database"),
                    schema=item.get("schema"),
                    dependencies=list(item.get("dependencies") or []),
                    comment=item.get("comment"),
                )
            )
        return out


def export_connector_to_dir(connector: LakehouseMetadataConnector, out_dir: str | Path) -> Path:
    """Materialize connector output as ingest-ready files under ``out_dir``."""
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    ddl_dir = root / "ddl"
    ddl_dir.mkdir(exist_ok=True)
    for idx, ddl in enumerate(connector.extract_ddl()):
        (ddl_dir / f"table_{idx:03d}.sql").write_text(ddl, encoding="utf-8")

    schema = [
        {
            "table": t.table,
            "database": t.database,
            "schema": t.schema,
            "comment": t.comment,
            "columns": [
                {
                    "name": c.name,
                    "type": c.type,
                    "comment": c.comment,
                    "nullable": c.nullable,
                }
                for c in t.columns
            ],
        }
        for t in connector.extract_schema()
    ]
    (root / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    views = [
        {
            "name": v.name,
            "sql": v.sql,
            "database": v.database,
            "schema": v.schema,
            "dependencies": v.dependencies,
            "comment": v.comment,
        }
        for v in connector.extract_views()
    ]
    (root / "views.json").write_text(
        json.dumps(views, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return root
