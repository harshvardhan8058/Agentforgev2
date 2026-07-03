"""Unit tests for the error envelope: 404 routing and 500 handling (Req 2.2, 2.5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agentforge.api.errors import register_exception_handlers
from agentforge.main import create_app


def _client_without_lifespan(app):
    # Not using `with`, so the lifespan (DB/Redis/migrations) does not run.
    return TestClient(app, raise_server_exceptions=False)


def test_unknown_route_returns_404_envelope():
    app = create_app()
    client = _client_without_lifespan(app)

    resp = client.get("/no/such/route")

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]
    assert "details" in body["error"]


def test_unhandled_exception_returns_500_envelope_without_stack_trace():
    app = create_app()

    @app.get("/boom")
    async def boom():  # pragma: no cover - exercised via the request
        raise RuntimeError("super secret internal detail")

    # Handlers were registered in create_app; re-register is idempotent-safe here.
    register_exception_handlers(app)
    client = _client_without_lifespan(app)

    resp = client.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["code"] == "internal_error"
    # The internal exception text / stack trace must never leak (Req 2.5).
    assert "super secret internal detail" not in resp.text
    assert "Traceback" not in resp.text
