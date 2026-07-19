"""API layer tests: GET /ingest/queue-metrics endpoint contract.

Verifies:
- Returns 200 + three queues (router/knowhere/pixelrag).
- concurrency aligns with settings.celery.queues.
- size is null when Redis is unreachable (still 200).
- size is the LLEN value when Redis is reachable.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from eagle_rag.api.app import app
from eagle_rag.config import get_settings


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def _queue_map() -> dict[str, int]:
    """Read the expected concurrency map from settings."""
    cfg = get_settings().celery
    return {name: q.concurrency for name, q in cfg.queues.items()}


def test_queue_metrics_returns_200_with_all_queues(client: TestClient) -> None:
    """GET /ingest/queue-metrics returns 200 with three queues; concurrency aligns with settings."""
    with patch("redis.Redis.from_url") as mock_from_url:
        mock_client = MagicMock()
        mock_client.llen.return_value = 0
        mock_from_url.return_value = mock_client
        resp = client.get("/ingest/queue-metrics")

    assert resp.status_code == 200
    body = resp.json()
    assert "queues" in body
    queues = body["queues"]
    expected = _queue_map()
    assert len(queues) == len(expected)
    by_name = {q["name"]: q for q in queues}
    for name, concurrency in expected.items():
        assert name in by_name, f"missing queue {name}"
        assert by_name[name]["concurrency"] == concurrency
        assert by_name[name]["size"] == 0


def test_queue_metrics_redis_down_size_is_null(client: TestClient) -> None:
    """Redis unreachable -> still returns 200; size is null."""
    with patch("redis.Redis.from_url", side_effect=Exception("redis down")):
        resp = client.get("/ingest/queue-metrics")

    assert resp.status_code == 200
    body = resp.json()
    for q in body["queues"]:
        assert q["size"] is None
        assert isinstance(q["concurrency"], int)


def test_queue_metrics_size_reflects_llen(client: TestClient) -> None:
    """size reflects the Redis LLEN value."""
    with patch("redis.Redis.from_url") as mock_from_url:
        mock_client = MagicMock()

        def _llen(qname: str) -> int:
            return {"router_queue": 2, "knowhere_queue": 5, "pixelrag_queue": 1}.get(qname, 0)

        mock_client.llen.side_effect = _llen
        mock_from_url.return_value = mock_client
        resp = client.get("/ingest/queue-metrics")

    assert resp.status_code == 200
    by_name = {q["name"]: q for q in resp.json()["queues"]}
    assert by_name["router_queue"]["size"] == 2
    assert by_name["knowhere_queue"]["size"] == 5
    assert by_name["pixelrag_queue"]["size"] == 1


def test_queue_metrics_default_concurrency_values(client: TestClient) -> None:
    """Default settings.yaml config: router=4 / knowhere=8 / pixelrag=1."""
    with patch("redis.Redis.from_url", side_effect=Exception("skip")):
        resp = client.get("/ingest/queue-metrics")

    assert resp.status_code == 200
    by_name = {q["name"]: q for q in resp.json()["queues"]}
    assert by_name["knowhere_queue"]["concurrency"] == 8
    assert by_name["pixelrag_queue"]["concurrency"] == 1
