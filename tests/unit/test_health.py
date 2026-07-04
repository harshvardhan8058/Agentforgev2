"""Unit tests for the health endpoints (Req 6.1, 6.2, 6.3, 6.4)."""

from __future__ import annotations

from fastapi.testclient import TestClient

import agentforge.api.routers.health as health_module
from agentforge.main import create_app


class _FakeRedis:
    def __init__(self, ok: bool) -> None:
        self._ok = ok

    async def ping(self) -> bool:
        if not self._ok:
            raise ConnectionError("redis down")
        return True


def _make_client(monkeypatch, *, db_up: bool, redis_up: bool) -> TestClient:
    app = create_app()

    async def fake_check_database(_engine) -> bool:
        return db_up

    monkeypatch.setattr(health_module, "check_database", fake_check_database)
    # Non-None engine so the readiness handler invokes the (patched) db check.
    app.state.db_engine = object()
    app.state.redis = _FakeRedis(redis_up)

    # No `with`: skip the real lifespan (migrations / real connections).
    return TestClient(app, raise_server_exceptions=False)


def test_liveness_always_200():
    app = create_app()
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "alive"


def test_readiness_200_when_all_dependencies_up(monkeypatch):
    client = _make_client(monkeypatch, db_up=True, redis_up=True)
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["dependencies"] == {"database": "up", "redis": "up"}


def test_readiness_503_lists_unavailable_dependency(monkeypatch):
    client = _make_client(monkeypatch, db_up=True, redis_up=False)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"]["database"] == "up"
    assert body["dependencies"]["redis"] == "down"


def test_readiness_503_when_all_down(monkeypatch):
    client = _make_client(monkeypatch, db_up=False, redis_up=False)
    resp = client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    assert body["dependencies"] == {"database": "down", "redis": "down"}
