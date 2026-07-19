"""KB stats Milvus namespace propagation tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from eagle_rag.kb import stats


def test_count_visual_safe_passes_instance_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(stats, "instance_namespace", lambda requested=None: "biomed")
    with patch("eagle_rag.index.milvus_visual_store.count_visual", return_value=5) as mock:
        assert stats._count_visual_safe("hutchmed") == 5
    mock.assert_called_once_with(kb_name="hutchmed", plugin_namespace="biomed")
