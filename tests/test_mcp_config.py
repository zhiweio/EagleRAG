"""MCP config (McpSettings) tests.

Verifies:
- ``Settings.mcp`` exists and defaults match cloud HTTP mode (transport=http,
  stateless_http=true, json_response=true, workers=4, auth_provider=static-token, port=8081, etc.).
- ``EAGLE_RAG_MCP__<FIELD>`` env vars can override defaults (transport / workers).
- Nested ``oauth`` / ``mtls`` sub-models default to disabled.
"""

from __future__ import annotations

import pytest

from eagle_rag.config import (
    _DEFAULT_SETTINGS_PATH,
    McpMtlsSettings,
    McpOAuthSettings,
    McpSettings,
    Settings,
    _load_yaml,
    get_settings,
)

# ---------------------------------------------------------------------------
# Isolation: override conftest.py autouse fixtures
#
# This test only exercises ``eagle_rag.config`` (which depends solely on yaml / pydantic /
# pydantic-settings, no heavy dependencies). The conftest.py autouse fixtures
# (``_reset_telemetry_state`` / ``_kb_registered``) would trigger heavy imports
# ``eagle_rag.kb`` -> ``eagle_rag.telemetry`` -> ``eagle_rag.tasks.celery_app``, which fail
# in a minimal environment without celery / opentelemetry pre-installed. Override them as
# no-ops so the config tests can run standalone.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    yield


@pytest.fixture(autouse=True)
def _kb_registered():
    yield


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def test_mcp_settings_defaults() -> None:
    """``McpSettings`` pure-model defaults match cloud HTTP mode."""
    mcp = McpSettings()
    assert mcp.transport == "http"
    assert mcp.streamable_http_path == "/mcp"
    assert mcp.stateless_http is True
    assert mcp.json_response is True
    assert mcp.standalone is False
    assert mcp.host == "0.0.0.0"
    assert mcp.port == 8081
    assert mcp.workers == 4
    assert mcp.tool_timeout == 30.0
    assert mcp.max_retries == 3
    assert mcp.circuit_fail_threshold == 5
    assert mcp.cache_ttl == 300
    assert mcp.event_store_enabled is False
    assert mcp.redis_url == ""
    assert mcp.auth_provider == "static-token"


def test_settings_mcp_attached_via_yaml() -> None:
    """``get_settings().mcp`` loaded via YAML matches the defaults."""
    mcp = get_settings().mcp
    assert mcp.transport == "http"
    assert mcp.stateless_http is True
    assert mcp.json_response is True
    assert mcp.workers == 4
    assert mcp.port == 8081
    assert mcp.auth_provider == "static-token"
    assert mcp.streamable_http_path == "/mcp"


# ---------------------------------------------------------------------------
# Nested oauth / mtls default disabled
# ---------------------------------------------------------------------------


def test_nested_oauth_mtls_default_disabled() -> None:
    """``oauth`` and ``mtls`` sub-models default to disabled."""
    mcp = McpSettings()
    assert isinstance(mcp.oauth, McpOAuthSettings)
    assert isinstance(mcp.mtls, McpMtlsSettings)
    assert mcp.oauth.enabled is False
    assert mcp.oauth.issuer_url == ""
    assert mcp.oauth.client_id == ""
    assert mcp.oauth.client_secret == ""
    assert mcp.oauth.required_scopes == []
    assert mcp.mtls.enabled is False


def test_nested_oauth_mtls_default_disabled_via_yaml() -> None:
    """``oauth`` / ``mtls`` loaded via YAML also default to disabled."""
    mcp = get_settings().mcp
    assert mcp.oauth.enabled is False
    assert mcp.oauth.required_scopes == []
    assert mcp.mtls.enabled is False


# ---------------------------------------------------------------------------
# Env var override (EAGLE_RAG_MCP__<FIELD>)
# ---------------------------------------------------------------------------


def _build_settings_without_mcp_kwargs() -> Settings:
    """Load from YAML but strip the ``mcp`` key so ``EAGLE_RAG_MCP__*`` env vars override defaults.

    In pydantic-settings, init kwargs take precedence over env vars; ``get_settings()`` passes
    the YAML ``mcp`` dict as init kwargs, which would shadow env var overrides. Here we drop the
    ``mcp`` key so ``Settings.mcp`` falls back to the default ``McpSettings()``, allowing env
    vars to override individual sub-fields.
    """
    data = _load_yaml(_DEFAULT_SETTINGS_PATH)
    data.pop("mcp", None)
    return Settings(**data)


def test_env_var_override_transport_and_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    """``EAGLE_RAG_MCP__TRANSPORT`` and ``EAGLE_RAG_MCP__WORKERS`` override defaults."""
    monkeypatch.setenv("EAGLE_RAG_MCP__TRANSPORT", "stdio")
    monkeypatch.setenv("EAGLE_RAG_MCP__WORKERS", "8")

    settings = _build_settings_without_mcp_kwargs()
    assert settings.mcp.transport == "stdio"
    assert settings.mcp.workers == 8
    # Non-overridden fields keep their defaults.
    assert settings.mcp.stateless_http is True
    assert settings.mcp.port == 8081


def test_env_var_override_port_and_auth_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """``EAGLE_RAG_MCP__PORT`` and ``EAGLE_RAG_MCP__AUTH_PROVIDER`` override defaults."""
    monkeypatch.setenv("EAGLE_RAG_MCP__PORT", "9090")
    monkeypatch.setenv("EAGLE_RAG_MCP__AUTH_PROVIDER", "oauth-github")

    settings = _build_settings_without_mcp_kwargs()
    assert settings.mcp.port == 9090
    assert settings.mcp.auth_provider == "oauth-github"
