"""Tests for Knowhere dual-mode parse dispatch (api vs parser)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from eagle_rag.ingest.knowhere_adapter import (
    KnowhereError,
    _parsing_params_to_parse_options,
    parse_with_knowhere_sdk,
)


def test_parsing_params_to_parse_options_maps_booleans() -> None:
    options = _parsing_params_to_parse_options(
        {
            "smart_title_parse": "true",
            "summary_image": "false",
            "doc_type": "auto",
            "model": "advanced",
            "ocr_enabled": True,
        }
    )
    assert options.smart_title_parse is True
    assert options.summary_image is False
    assert options.doc_type == "auto"


def test_parsing_params_to_parse_options_empty() -> None:
    options = _parsing_params_to_parse_options({})
    assert options.smart_title_parse is True
    assert options.summary_txt is True


@patch("eagle_rag.ingest.knowhere_adapter.get_settings")
@patch("eagle_rag.ingest.knowhere_adapter._parse_via_api_sdk")
def test_parse_dispatches_api_mode(mock_api: MagicMock, mock_settings: MagicMock) -> None:
    mock_settings.return_value.knowhere.mode = "api"
    fake_result = SimpleNamespace(chunks=[])
    mock_api.return_value = fake_result

    result = parse_with_knowhere_sdk("/tmp/doc.pdf", file_name="doc.pdf")

    mock_api.assert_called_once_with("/tmp/doc.pdf", file_name="doc.pdf", kb_name=None)
    assert result is fake_result


@patch("eagle_rag.ingest.knowhere_adapter.get_settings")
@patch("eagle_rag.ingest.knowhere_adapter._parse_via_parser_sdk")
def test_parse_dispatches_parser_mode(mock_parser: MagicMock, mock_settings: MagicMock) -> None:
    mock_settings.return_value.knowhere.mode = "parser"
    fake_result = SimpleNamespace(chunks=[])
    mock_parser.return_value = fake_result

    result = parse_with_knowhere_sdk(
        "/tmp/doc.pdf",
        file_name="doc.pdf",
        kb_name="finance",
    )

    mock_parser.assert_called_once_with(
        "/tmp/doc.pdf",
        file_name="doc.pdf",
        kb_name="finance",
    )
    assert result is fake_result


@patch("eagle_rag.ingest.knowhere_adapter._build_parser_config")
@patch("eagle_rag.ingest.knowhere_adapter.get_settings")
def test_parse_via_parser_sdk_wraps_parse_error(
    mock_settings: MagicMock,
    mock_build_config: MagicMock,
) -> None:
    from knowhere_parse.exceptions import ParseError

    from eagle_rag.ingest import knowhere_adapter

    kh = mock_settings.return_value.knowhere
    kh.mode = "parser"
    kh.parsing_params = {}
    kh.parser.use_llm_nav_summary = True
    mock_build_config.return_value = SimpleNamespace(tmp_path="/tmp/knowhere-parse")

    with patch("knowhere_parse.KnowhereParser") as mock_cls:
        mock_cls.return_value.parse.side_effect = ParseError("pipeline failed")
        with pytest.raises(KnowhereError, match="parser SDK call failed"):
            knowhere_adapter._parse_via_parser_sdk(
                str(Path("/tmp/doc.pdf")),
                file_name="doc.pdf",
            )
