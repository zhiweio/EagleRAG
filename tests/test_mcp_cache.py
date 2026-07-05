"""MCP Redis cache (``eagle_rag.mcp_cache``) tests.

Verifies cache keying, Redis get/set behavior, silent degradation, and tool integration:

- **cache_key**: ``scope`` is sorted before hashing (different order -> same key);
  different arguments -> different keys; ``kb_name=None`` is normalized to empty string.
- **get_cached / set_cached**: mock the Redis connection pool and verify hit / miss /
  setex call arguments (key / ttl / JSON serialization).
- **Silent degradation**: when Redis is unreachable, ``get_cached`` returns ``None``
  and ``set_cached`` does not raise.
- **No Redis configured**: when both ``redis_url`` and ``celery.broker_url`` are empty,
  ``_get_redis()`` returns ``None`` and every cache lookup is a miss.
- **Tool integration**: ``retrieve_text`` skips the service layer on a cache hit.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from eagle_rag.mcp_cache import (
    cache_key,
    get_cached,
    reset_redis_pool,
    set_cached,
)

# ---------------------------------------------------------------------------
# Isolation: override conftest.py autouse fixtures (same as test_mcp_config.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    yield


@pytest.fixture(autouse=True)
def _kb_registered():
    yield


# ---------------------------------------------------------------------------
# mock settings + reset connection pool
# ---------------------------------------------------------------------------


def _make_settings(*, redis_url="", broker_url="redis://localhost:6379/0", cache_ttl=300):
    """Build a SimpleNamespace with ``mcp`` and ``celery`` sub-objects."""
    mcp = SimpleNamespace(redis_url=redis_url, cache_ttl=cache_ttl)
    celery = SimpleNamespace(broker_url=broker_url)
    return SimpleNamespace(mcp=mcp, celery=celery)


@pytest.fixture(autouse=True)
def _mock_settings():
    """Mock ``eagle_rag.mcp_cache.get_settings`` to return default settings."""
    settings = _make_settings()
    with patch("eagle_rag.mcp_cache.get_settings", return_value=settings):
        yield


@pytest.fixture(autouse=True)
def _reset_pool():
    """Reset the Redis connection pool cache before and after each test."""
    reset_redis_pool()
    yield
    reset_redis_pool()


# ---------------------------------------------------------------------------
# 1. cache_key
# ---------------------------------------------------------------------------


def test_cache_key_deterministic() -> None:
    """Same arguments produce the same key."""
    k1 = cache_key("retrieve_text", "个税", scope=["d1", "d2"], top_k=5, kb_name="kb1")
    k2 = cache_key("retrieve_text", "个税", scope=["d1", "d2"], top_k=5, kb_name="kb1")
    assert k1 == k2


def test_cache_key_scope_order_invariant() -> None:
    """``scope`` order does not affect the key (sorted before hashing)."""
    k1 = cache_key("retrieve_text", "q", scope=["d2", "d1", "d3"], top_k=5)
    k2 = cache_key("retrieve_text", "q", scope=["d1", "d3", "d2"], top_k=5)
    assert k1 == k2


def test_cache_key_different_query_different_key() -> None:
    """Different queries produce different keys."""
    k1 = cache_key("retrieve_text", "个税起征点", top_k=5)
    k2 = cache_key("retrieve_text", "增值税率", top_k=5)
    assert k1 != k2


def test_cache_key_different_tool_different_key() -> None:
    """Different tools produce different keys."""
    k1 = cache_key("retrieve_text", "q", top_k=5)
    k2 = cache_key("retrieve_visual", "q", top_k=5)
    assert k1 != k2


def test_cache_key_none_scope_and_kb_name() -> None:
    """``scope=None`` / ``kb_name=None`` do not raise and normalize to empty."""
    k1 = cache_key("retrieve_text", "q", scope=None, top_k=5, kb_name=None)
    k2 = cache_key("retrieve_text", "q", scope=[], top_k=5, kb_name="")
    assert k1 == k2


def test_cache_key_format() -> None:
    """Key format is ``mcp:{tool}:{sha256_hex}``."""
    key = cache_key("retrieve_text", "q", top_k=5)
    parts = key.split(":")
    assert parts[0] == "mcp"
    assert parts[1] == "retrieve_text"
    assert len(parts[2]) == 64  # SHA-256 hex


# ---------------------------------------------------------------------------
# 2. get_cached / set_cached — mock Redis
# ---------------------------------------------------------------------------


def _mock_redis_factory():
    """Build a mock redis module + ConnectionPool + Redis client."""
    fake_client = MagicMock()
    fake_pool = MagicMock()
    fake_redis_module = MagicMock()
    fake_redis_module.ConnectionPool.from_url.return_value = fake_pool
    fake_redis_module.Redis.return_value = fake_client
    fake_redis_module.RedisError = Exception
    return fake_redis_module, fake_pool, fake_client


def test_set_cached_writes_to_redis() -> None:
    """``set_cached`` writes via ``client.setex(key, ttl, json)``."""
    fake_module, fake_pool, fake_client = _mock_redis_factory()
    import sys

    original_redis = sys.modules.get("redis")
    sys.modules["redis"] = fake_module
    try:
        set_cached("mcp:test:key", {"data": [1, 2, 3]}, ttl=120)
    finally:
        if original_redis is not None:
            sys.modules["redis"] = original_redis
        else:
            sys.modules.pop("redis", None)

    fake_module.ConnectionPool.from_url.assert_called_once()
    fake_module.Redis.assert_called_once()
    fake_client.setex.assert_called_once()
    args = fake_client.setex.call_args
    assert args[0][0] == "mcp:test:key"
    assert args[0][1] == 120
    assert json.loads(args[0][2]) == {"data": [1, 2, 3]}


def test_get_cached_returns_value_on_hit() -> None:
    """``get_cached`` returns the deserialized value on a cache hit."""
    fake_module, fake_pool, fake_client = _mock_redis_factory()
    fake_client.get.return_value = json.dumps([{"node_id": "n1", "text": "hello"}])
    import sys

    original_redis = sys.modules.get("redis")
    sys.modules["redis"] = fake_module
    try:
        result = get_cached("mcp:test:key")
    finally:
        if original_redis is not None:
            sys.modules["redis"] = original_redis
        else:
            sys.modules.pop("redis", None)

    assert result == [{"node_id": "n1", "text": "hello"}]


def test_get_cached_returns_none_on_miss() -> None:
    """``get_cached`` returns ``None`` on a miss."""
    fake_module, fake_pool, fake_client = _mock_redis_factory()
    fake_client.get.return_value = None
    import sys

    original_redis = sys.modules.get("redis")
    sys.modules["redis"] = fake_module
    try:
        result = get_cached("mcp:test:miss")
    finally:
        if original_redis is not None:
            sys.modules["redis"] = original_redis
        else:
            sys.modules.pop("redis", None)

    assert result is None


# ---------------------------------------------------------------------------
# 3. Silent degradation
# ---------------------------------------------------------------------------


def test_get_cached_silent_degradation_on_redis_error() -> None:
    """When Redis raises, ``get_cached`` returns ``None`` instead of propagating."""
    fake_module, fake_pool, fake_client = _mock_redis_factory()
    fake_client.get.side_effect = ConnectionError("redis down")
    import sys

    original_redis = sys.modules.get("redis")
    sys.modules["redis"] = fake_module
    try:
        result = get_cached("mcp:test:key")
    finally:
        if original_redis is not None:
            sys.modules["redis"] = original_redis
        else:
            sys.modules.pop("redis", None)

    assert result is None


def test_set_cached_silent_degradation_on_redis_error() -> None:
    """When Redis raises, ``set_cached`` swallows the exception."""
    fake_module, fake_pool, fake_client = _mock_redis_factory()
    fake_client.setex.side_effect = ConnectionError("redis down")
    import sys

    original_redis = sys.modules.get("redis")
    sys.modules["redis"] = fake_module
    try:
        set_cached("mcp:test:key", {"data": 1}, ttl=60)
    finally:
        if original_redis is not None:
            sys.modules["redis"] = original_redis
        else:
            sys.modules.pop("redis", None)


def test_no_redis_url_returns_none() -> None:
    """When both ``redis_url`` and ``broker_url`` are empty, ``get_cached`` returns ``None``."""
    settings = _make_settings(redis_url="", broker_url="")
    with patch("eagle_rag.mcp_cache.get_settings", return_value=settings):
        reset_redis_pool()
        assert get_cached("anykey") is None
        set_cached("anykey", {"x": 1}, ttl=10)  # should not raise


# ---------------------------------------------------------------------------
# 4. Tool integration: retrieve_text cache hit skips service layer
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_record_mcp_call():
    """Mock ``record_mcp_call`` to avoid DB dependency."""
    with patch("eagle_rag.admin.mcp_log.record_mcp_call"):
        yield


def test_retrieve_text_cache_hit_skips_service(_mock_record_mcp_call) -> None:
    """``retrieve_text`` does not invoke ``KnowhereGraphRetriever`` on a cache hit."""
    cached_result = [{"node_id": "n1", "text": "cached", "score": 0.9, "metadata": {}}]
    with (
        patch("eagle_rag.api.mcp_server.get_cached", return_value=cached_result),
        patch("eagle_rag.api.mcp_server.set_cached") as mock_set,
        patch(
            "eagle_rag.retrievers.knowhere_graph_retriever.KnowhereGraphRetriever"
        ) as mock_retriever_cls,
    ):
        from eagle_rag.api.mcp_server import retrieve_text

        result = retrieve_text("个税起征点", top_k=5)

    assert result == cached_result
    # Service layer not invoked.
    mock_retriever_cls.assert_not_called()
    # Cache write not triggered on a hit (no write-back).
    mock_set.assert_not_called()


def test_retrieve_text_cache_miss_calls_service_and_writes_back(_mock_record_mcp_call) -> None:
    """``retrieve_text`` invokes the service layer on a miss and writes the result back to cache."""
    from types import SimpleNamespace as NS

    fake_node = NS(
        node_id="n1",
        metadata={"path": "p", "level": 1, "summary": "s", "document_id": "d1", "source_type": "t"},
    )
    fake_node.get_content = MagicMock(return_value="text content")
    fake_nws = NS(node=fake_node, score=0.95)
    fake_retriever = MagicMock()
    fake_retriever.retrieve.return_value = [fake_nws]

    with (
        patch("eagle_rag.api.mcp_server.get_cached", return_value=None),
        patch("eagle_rag.api.mcp_server.set_cached") as mock_set,
        patch(
            "eagle_rag.retrievers.knowhere_graph_retriever.KnowhereGraphRetriever",
            return_value=fake_retriever,
        ),
    ):
        from eagle_rag.api.mcp_server import retrieve_text

        result = retrieve_text("个税起征点", top_k=5)

    assert len(result) == 1
    assert result[0]["node_id"] == "n1"
    # Cache write triggered.
    mock_set.assert_called_once()
    # Written value is the processed out list.
    written_value = mock_set.call_args[0][1]
    assert len(written_value) == 1
    assert written_value[0]["node_id"] == "n1"


def test_retrieve_visual_cache_hit_skips_service(_mock_record_mcp_call) -> None:
    """``retrieve_visual`` does not invoke ``PixelRAGVisualRetriever`` on a cache hit."""
    cached_result = [
        {"image_id": "img1", "document_id": "d1", "page": 1, "position": 0, "score": 0.8}
    ]
    with (
        patch("eagle_rag.api.mcp_server.get_cached", return_value=cached_result),
        patch("eagle_rag.api.mcp_server.set_cached") as mock_set,
        patch(
            "eagle_rag.retrievers.pixelrag_visual_retriever.PixelRAGVisualRetriever"
        ) as mock_retriever_cls,
    ):
        from eagle_rag.api.mcp_server import retrieve_visual

        result = retrieve_visual("图表", top_k=5)

    assert result == cached_result
    mock_retriever_cls.assert_not_called()
    mock_set.assert_not_called()
