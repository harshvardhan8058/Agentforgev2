"""Unit tests for the error envelope: 404 routing and 500 handling (Req 2.2, 2.5)."""

from __future__ import annotations

from fastapi import Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.testclient import TestClient

from agentforge.api.errors import (
    AppError,
    defer_after_error,
    register_exception_handlers,
)
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



# --- deferred post-error work -----------------------------------------------------
#
# The success paths have FastAPI's BackgroundTasks; the error paths had nothing, because a
# raised AppError never produces a response to hang work on. These tests pin the seam that
# closes that gap, including the case that actually occurs in production: registration from a
# worker thread, since the code that raises runs under `run_in_threadpool`.


def test_deferred_work_runs_after_an_app_error_response():
    app = create_app()
    ran: list[str] = []

    @app.get("/deferred-boom")
    async def deferred_boom(request: Request):  # pragma: no cover - via the request
        defer_after_error(request, lambda: ran.append("after"))
        raise AppError("blocked", "refused", status.HTTP_400_BAD_REQUEST)

    register_exception_handlers(app)
    resp = _client_without_lifespan(app).get("/deferred-boom")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "blocked"
    assert ran == ["after"]


def test_deferred_work_registered_from_a_worker_thread_still_runs():
    """The real shape: the raising code runs in a threadpool, the handler on the event loop."""
    app = create_app()
    ran: list[str] = []

    @app.get("/deferred-threadpool")
    async def deferred_threadpool(request: Request):  # pragma: no cover - via the request
        def _work():
            defer_after_error(request, lambda: ran.append("after"))
            raise AppError("blocked", "refused", status.HTTP_400_BAD_REQUEST)

        await run_in_threadpool(_work)

    register_exception_handlers(app)
    resp = _client_without_lifespan(app).get("/deferred-threadpool")

    assert resp.status_code == 400
    assert ran == ["after"]


def test_every_deferred_task_runs_even_when_one_fails():
    """They are independent side effects, not a transaction."""
    app = create_app()
    ran: list[str] = []

    @app.get("/deferred-many")
    async def deferred_many(request: Request):  # pragma: no cover - via the request
        defer_after_error(request, lambda: ran.append("first"))

        def _explode():
            raise RuntimeError("side effect failed")

        defer_after_error(request, _explode)
        defer_after_error(request, lambda: ran.append("third"))
        raise AppError("blocked", "refused", status.HTTP_400_BAD_REQUEST)

    register_exception_handlers(app)
    resp = _client_without_lifespan(app).get("/deferred-many")

    assert resp.status_code == 400
    assert ran == ["first", "third"]


def test_a_failing_deferred_task_does_not_change_the_response():
    app = create_app()

    @app.get("/deferred-fails")
    async def deferred_fails(request: Request):  # pragma: no cover - via the request
        def _explode():
            raise RuntimeError("secret internal detail")

        defer_after_error(request, _explode)
        raise AppError("blocked", "refused", status.HTTP_400_BAD_REQUEST, {"reason": "x"})

    register_exception_handlers(app)
    resp = _client_without_lifespan(app).get("/deferred-fails")

    assert resp.status_code == 400
    assert resp.json()["error"]["details"] == {"reason": "x"}
    assert "secret internal detail" not in resp.text


def test_an_app_error_without_deferred_work_is_unchanged():
    app = create_app()

    @app.get("/plain-boom")
    async def plain_boom():  # pragma: no cover - via the request
        raise AppError("blocked", "refused", status.HTTP_400_BAD_REQUEST)

    register_exception_handlers(app)
    resp = _client_without_lifespan(app).get("/plain-boom")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "blocked"
