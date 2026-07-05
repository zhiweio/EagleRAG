"""MCP auth (configure_mcp_auth) tests.

Verifies auth provider selection and configuration fallbacks:
- ``auth.enabled=false`` -> no auth (``mcp.auth=None``).
- ``auth_provider="static-token"`` -> ``StaticTokenVerifier`` validating
  ``Authorization: Bearer <api_key>``; the API key is injected via
  ``auth.api_key`` or ``AUTH_API_KEY_FILE`` (Docker Swarm secret).
- ``auth_provider="oauth-github"`` -> ``GitHubProvider`` (when config is complete).
- ``auth_provider="oauth-custom"`` -> ``JWTVerifier`` (when config is complete).
- Incomplete config / unknown provider -> auth disabled (``mcp.auth=None``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from eagle_rag.api.mcp_server import configure_mcp_auth, mcp

# ---------------------------------------------------------------------------
# Isolation: override conftest.py autouse fixtures (same rationale as test_mcp_config.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    yield


@pytest.fixture(autouse=True)
def _kb_registered():
    yield


@pytest.fixture(autouse=True)
def _reset_mcp_auth():
    """Clear ``mcp.auth`` before and after each test to avoid cross-test leakage."""
    mcp.auth = None
    yield
    mcp.auth = None


@pytest.fixture(autouse=True)
def _clear_auth_env(monkeypatch: pytest.MonkeyPatch):
    """Clear ``AUTH_API_KEY_FILE`` and similar env vars to avoid host contamination."""
    monkeypatch.delenv("AUTH_API_KEY_FILE", raising=False)


def _make_settings(
    *,
    auth_enabled: bool = False,
    api_key: str = "",
    auth_provider: str = "static-token",
    oauth_enabled: bool = False,
    oauth_issuer_url: str = "",
    oauth_client_id: str = "",
    oauth_client_secret: str = "",
    oauth_required_scopes: list[str] | None = None,
    mcp_port: int = 8081,
) -> SimpleNamespace:
    """Build a settings stand-in exposing only the fields accessed by ``configure_mcp_auth``."""
    oauth = SimpleNamespace(
        enabled=oauth_enabled,
        issuer_url=oauth_issuer_url,
        client_id=oauth_client_id,
        client_secret=oauth_client_secret,
        required_scopes=oauth_required_scopes or [],
    )
    mcp_cfg = SimpleNamespace(
        auth_provider=auth_provider,
        oauth=oauth,
        port=mcp_port,
    )
    auth = SimpleNamespace(enabled=auth_enabled, api_key=api_key)
    return SimpleNamespace(auth=auth, mcp=mcp_cfg)


# ---------------------------------------------------------------------------
# 1. auth.enabled=false -> no auth
# ---------------------------------------------------------------------------


def test_auth_disabled_returns_none() -> None:
    """``auth.enabled=false`` -> returns None and leaves ``mcp.auth`` as None."""
    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(auth_enabled=False),
    ):
        result = configure_mcp_auth()
    assert result is None
    assert mcp.auth is None


# ---------------------------------------------------------------------------
# 2. static-token
# ---------------------------------------------------------------------------


def test_static_token_with_valid_api_key() -> None:
    """``auth_provider=static-token`` + non-empty api_key -> StaticTokenVerifier."""
    from fastmcp.server.auth import StaticTokenVerifier

    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(
            auth_enabled=True, api_key="secret-key-123", auth_provider="static-token"
        ),
    ):
        result = configure_mcp_auth()

    assert isinstance(result, StaticTokenVerifier)
    assert mcp.auth is result
    # Token dict contains the supplied api_key.
    assert "secret-key-123" in result.tokens
    token_meta = result.tokens["secret-key-123"]
    assert token_meta["client_id"] == "eagle-rag"
    assert token_meta["scopes"] == ["eagle-rag:tools"]
    # required_scopes is enforced (TokenVerifier base class stores it as list/set; assert
    # membership).
    assert "eagle-rag:tools" in result.required_scopes


def test_static_token_empty_api_key_returns_none() -> None:
    """``auth.enabled=true`` but empty api_key -> auth disabled."""
    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(auth_enabled=True, api_key="", auth_provider="static-token"),
    ):
        result = configure_mcp_auth()
    assert result is None
    assert mcp.auth is None


def test_static_token_reads_api_key_file(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``AUTH_API_KEY_FILE`` content is used as the api_key (Docker Swarm secret)."""
    from fastmcp.server.auth import StaticTokenVerifier

    secret_file = tmp_path / "mcp_api_key"
    secret_file.write_text("swarm-secret-key\n", encoding="utf-8")
    monkeypatch.setenv("AUTH_API_KEY_FILE", str(secret_file))

    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(auth_enabled=True, api_key="", auth_provider="static-token"),
    ):
        result = configure_mcp_auth()

    assert isinstance(result, StaticTokenVerifier)
    # File content is stripped and registered as a valid token.
    assert "swarm-secret-key" in result.tokens


def test_static_token_api_key_env_takes_precedence_over_file(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``auth.api_key`` (env AUTH_API_KEY) takes precedence over ``AUTH_API_KEY_FILE``."""
    from fastmcp.server.auth import StaticTokenVerifier

    secret_file = tmp_path / "mcp_api_key"
    secret_file.write_text("file-secret", encoding="utf-8")
    monkeypatch.setenv("AUTH_API_KEY_FILE", str(secret_file))

    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(
            auth_enabled=True, api_key="env-secret", auth_provider="static-token"
        ),
    ):
        result = configure_mcp_auth()

    assert isinstance(result, StaticTokenVerifier)
    # env api_key wins.
    assert "env-secret" in result.tokens
    assert "file-secret" not in result.tokens


@pytest.mark.asyncio
async def test_static_token_verifier_validates_correct_token() -> None:
    """StaticTokenVerifier accepts the correct token and rejects the wrong one."""
    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(
            auth_enabled=True, api_key="valid-key", auth_provider="static-token"
        ),
    ):
        verifier = configure_mcp_auth()

    assert verifier is not None
    # Correct token -> AccessToken.
    access = await verifier.verify_token("valid-key")
    assert access is not None
    assert access.client_id == "eagle-rag"
    assert "eagle-rag:tools" in access.scopes
    # Wrong token -> None.
    assert await verifier.verify_token("wrong-key") is None


# ---------------------------------------------------------------------------
# 3. oauth-github
# ---------------------------------------------------------------------------


def test_oauth_github_incomplete_config_returns_none() -> None:
    """``oauth-github`` with oauth.enabled=false / missing client_id -> auth disabled."""
    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(
            auth_enabled=True,
            auth_provider="oauth-github",
            oauth_enabled=False,
        ),
    ):
        result = configure_mcp_auth()
    assert result is None
    assert mcp.auth is None


def test_oauth_github_complete_config_returns_provider() -> None:
    """``oauth-github`` with complete config -> GitHubProvider (base_url from issuer_url)."""
    from fastmcp.server.auth.providers.github import GitHubProvider

    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(
            auth_enabled=True,
            auth_provider="oauth-github",
            oauth_enabled=True,
            oauth_client_id="gh-client-id",
            oauth_client_secret="gh-client-secret",
            oauth_issuer_url="https://mcp.example.com",
            oauth_required_scopes=["user"],
        ),
    ):
        result = configure_mcp_auth()

    assert isinstance(result, GitHubProvider)
    assert mcp.auth is result


# ---------------------------------------------------------------------------
# 4. oauth-custom
# ---------------------------------------------------------------------------


def test_oauth_custom_incomplete_config_returns_none() -> None:
    """``oauth-custom`` with empty issuer_url -> auth disabled."""
    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(
            auth_enabled=True,
            auth_provider="oauth-custom",
            oauth_enabled=True,
            oauth_issuer_url="",
        ),
    ):
        result = configure_mcp_auth()
    assert result is None
    assert mcp.auth is None


def test_oauth_custom_complete_config_returns_jwt_verifier() -> None:
    """``oauth-custom`` with complete config -> JWTVerifier (jwks_uri derived from issuer_url)."""
    from fastmcp.server.auth import JWTVerifier

    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(
            auth_enabled=True,
            auth_provider="oauth-custom",
            oauth_enabled=True,
            oauth_issuer_url="https://idp.example.com",
            oauth_required_scopes=["eagle-rag:tools"],
        ),
    ):
        result = configure_mcp_auth()

    assert isinstance(result, JWTVerifier)
    assert mcp.auth is result
    assert result.jwks_uri == "https://idp.example.com/.well-known/jwks.json"
    assert result.issuer == "https://idp.example.com"


# ---------------------------------------------------------------------------
# 5. Unknown provider
# ---------------------------------------------------------------------------


def test_unknown_provider_returns_none() -> None:
    """Unknown auth_provider -> auth disabled."""
    with patch(
        "eagle_rag.config.get_settings",
        return_value=_make_settings(auth_enabled=True, auth_provider="unknown", api_key="x"),
    ):
        result = configure_mcp_auth()
    assert result is None
    assert mcp.auth is None
