"""Unit tests for the error envelope: 404 routing and 500 handling (Req 2.2, 2.5)."""

from __future__ import annotations

from fastapi import Request, status
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



# --- work that must still happen when the response is an error ---------------------
#
# FastAPI's BackgroundTasks are attached to the response an endpoint *returns*, so an
# endpoint that raises loses them. Some follow-up work is owed regardless of the status
# (a guardrail refusal is a real, reportable security event), which is what
# ``defer_after_error`` exists for.


def _app_with_deferred_route(tasks_to_register, *, raise_app_error=True):
    """Build an app whose one route registers deferred work and then fails (or succeeds).

    ``Request`` is imported at module scope on purpose: with ``from __future__ import
    annotations`` in effect, FastAPI resolves a handler's annotations against its module
    globals, so a locally-imported name would be unresolvable and the parameter would be
    mistaken for a query string field.
    """
    app = create_app()

    @app.get("/deferred")
    async def deferred(request: Request):  # pragma: no cover - exercised via the request
        for task in tasks_to_register:
            defer_after_error(request, task)
        if raise_app_error:
            raise AppError("guardrail_blocked", "nope", status.HTTP_400_BAD_REQUEST)
        return {"ok": True}

    register_exception_handlers(app)
    return _client_without_lifespan(app)


def test_deferred_work_runs_after_an_app_error_response():
    ran: list[str] = []
    client = _app_with_deferred_route([lambda: ran.append("reported")])

    resp = client.get("/deferred")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "guardrail_blocked"
    assert ran == ["reported"]


def test_every_deferred_task_runs_even_if_one_fails():
    """One notification failing must not cancel the others."""
    ran: list[str] = []

    def explode() -> None:
        raise RuntimeError("reporting is broken")

    client = _app_with_deferred_route(
        [explode, lambda: ran.append("second"), lambda: ran.append("third")]
    )

    resp = client.get("/deferred")

    assert resp.status_code == 400
    assert ran == ["second", "third"]


def test_a_deferred_task_failure_does_not_change_the_error_body():
    def explode() -> None:
        raise RuntimeError("reporting is broken")

    client = _app_with_deferred_route([explode])

    resp = client.get("/deferred")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "guardrail_blocked"
    assert "reporting is broken" not in resp.text


def test_deferred_work_registered_on_a_successful_request_is_simply_not_run():
    """It is registered immediately before raising; a success means there was nothing to report."""
    ran: list[str] = []
    client = _app_with_deferred_route([lambda: ran.append("x")], raise_app_error=False)

    resp = client.get("/deferred")

    assert resp.status_code == 200
    assert ran == []


def test_a_request_that_registers_nothing_gets_a_plain_error_response():
    client = _app_with_deferred_route([])

    resp = client.get("/deferred")

    assert resp.status_code == 400
    assert resp.json()["error"] == {
        "code": "guardrail_blocked",
        "message": "nope",
        "details": {},
    }



def test_deferred_work_registered_from_a_worker_thread_still_runs():
    """The arrangement production actually uses.

    Every real call site registers from inside `run_in_threadpool` — the guardrail block happens
    in the worker running the synchronous pipeline — while the exception handler reads the list on
    the event loop. There is one writer per request and the threadpool future establishes the
    ordering, but the tests above all register from the event loop, so this is the case that
    matters and was otherwise unexercised.
    """
    from fastapi.concurrency import run_in_threadpool

    ran: list[str] = []
    app = create_app()

    @app.get("/deferred-from-worker")
    async def deferred_from_worker(request: Request):  # pragma: no cover - via the request
        def blocking_work() -> None:
            # Registered from the worker thread, exactly as `_report_block` does.
            defer_after_error(request, lambda: ran.append("reported"))

        await run_in_threadpool(blocking_work)
        raise AppError("guardrail_blocked", "nope", status.HTTP_400_BAD_REQUEST)

    register_exception_handlers(app)
    resp = _client_without_lifespan(app).get("/deferred-from-worker")

    assert resp.status_code == 400
    assert ran == ["reported"]
