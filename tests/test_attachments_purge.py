"""Non-image attachment purge unit tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from eagle_rag.attachments.store import purge_non_image_attachments_sync


def test_purge_non_image_attachments_sync_removes_pdf_and_scrubs_messages(tmp_path: Path):
    """Legacy PDF rows are deleted; PNG rows and message refs for removed IDs are cleaned."""
    pdf_path = tmp_path / "doc.pdf"
    png_path = tmp_path / "photo.png"
    pdf_path.write_bytes(b"%PDF-1.4")
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    pdf_id = "att-pdf"
    png_id = "att-png"
    attachment_rows = [
        (pdf_id, str(pdf_path), "application/pdf", "doc.pdf"),
        (png_id, str(png_path), "image/png", "photo.png"),
    ]
    message_rows = [("msg-1", [pdf_id, png_id]), ("msg-2", [png_id])]

    with (
        patch("eagle_rag.db.sync_fetchall") as mock_fetch,
        patch("eagle_rag.attachments.store.sync_execute") as mock_exec,
    ):
        mock_fetch.side_effect = [attachment_rows, message_rows]
        removed = purge_non_image_attachments_sync()

    assert removed == 1
    assert not pdf_path.exists()
    assert png_path.exists()

    delete_sql = [
        call for call in mock_exec.call_args_list if "DELETE FROM attachments" in call[0][0]
    ]
    assert len(delete_sql) == 1
    assert delete_sql[0][0][1] == (pdf_id,)

    update_sql = [call for call in mock_exec.call_args_list if "UPDATE messages" in call[0][0]]
    assert len(update_sql) == 1
    assert update_sql[0][0][1][0] == json.dumps([png_id])
    assert update_sql[0][0][1][1] == "msg-1"


def test_purge_non_image_attachments_sync_noop_when_all_images():
    with (
        patch("eagle_rag.db.sync_fetchall") as mock_fetch,
        patch("eagle_rag.attachments.store.sync_execute") as mock_exec,
    ):
        mock_fetch.return_value = [
            ("att-png", "/tmp/photo.png", "image/png", "photo.png"),
        ]
        removed = purge_non_image_attachments_sync()

    assert removed == 0
    mock_exec.assert_not_called()
