"""Uniform error envelope and FastAPI exception handlers.

All error responses share the envelope ``{ "error": { code, message, details } }``.
Unknown routes return 404 ``not_found`` (Req 2.2) and unhandled exceptions return
500 ``internal_error`` without leaking a stack trace (Req 2.5).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Domain error carrying an HTTP status, a stable error code, and details.

    Used across the platform so handlers can render a consistent envelope without
    leaking internal exception text.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict:
    """Build the standard error envelope dict."""
    return {"error": {"code": code, "message": message, "details": details or {}}}


# Map well-known HTTP status codes to stable error codes for the envelope.
_STATUS_CODE_NAMES = {
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_405_METHOD_NOT_ALLOWED: "method_not_allowed",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "validation_error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "not_ready",
}


# Attribute on ``request.state`` holding work to run after an error response is sent. Named
# with a prefix because ``request.state`` is a shared namespace.
_DEFERRED_ATTR = "_agentforge_deferred_after_error"


def defer_after_error(request: Request, task: Callable[[], None]) -> None:
    """Register ``task`` to run *after* the error response for this request is sent.

    The success paths already have a seam for after-the-response work — FastAPI's
    ``BackgroundTasks`` — and the error paths had none, because a ``BackgroundTasks`` instance
    is attached to a response that raising never produces. That gap mattered as soon as
    something needed to be *reported* about a refusal: a guardrail block is exactly the event
    an operator wants a webhook for, and emitting it inline would put a tenant's endpoint (up
    to the full retry budget) in front of a 400 the caller is already waiting on.

    So the work is parked on the request and picked up by :func:`_app_error_handler`, which is
    the one place that turns an :class:`AppError` into a response. Registration is safe from a
    worker thread (the usual case: the raising code runs under ``run_in_threadpool``) because
    there is a single writer per request and the handler reads it only after that thread's
    future has resolved.

    Only :class:`AppError` responses honour the queue. That is the intended scope — a deferred
    task is registered by the code that is about to raise an ``AppError`` — and anything else
    reaching the caller means the request failed in a way that is its own bigger problem.
    """
    tasks = getattr(request.state, _DEFERRED_ATTR, None)
    if tasks is None:
        tasks = []
        setattr(request.state, _DEFERRED_ATTR, tasks)
    tasks.append(task)


def _run_deferred(tasks: list[Callable[[], None]]) -> None:
    """Run every deferred task, absorbing failures individually.

    Synchronous, so Starlette runs it in a worker thread after the response is sent. One task
    failing must not skip the rest: they are independent side effects, not a transaction.
    """
    for task in tasks:
        try:
            task()
        except Exception:  # noqa: BLE001 - post-response work must not escape
            logger.warning("Deferred post-error task failed.", exc_info=True)


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    tasks = getattr(request.state, _DEFERRED_ATTR, None)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.details),
        # Starlette runs this after the response has been sent, which is the whole point.
        background=BackgroundTask(_run_deferred, tasks) if tasks else None,
    )


async def _http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = _STATUS_CODE_NAMES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    return JSONResponse(status_code=exc.status_code, content=error_body(code, message))


# Keys of a pydantic error entry that are safe to return. `input` is deliberately absent:
# it is the caller's own submitted value, and echoing it turns any validation failure into a
# reflection of whatever was sent — including a credential pasted into a field that then
# failed type validation. `loc` + `msg` + `type` are what a client needs to point at the
# offending field, and `loc` never contains a value (only field names and indices).
_SAFE_VALIDATION_ERROR_KEYS = ("type", "loc", "msg")


def _safe_validation_errors(errors: list) -> list[dict]:
    """Strip the echoed input from pydantic's error entries (Req 2.5).

    ``ctx`` is dropped as well: for several pydantic error types it embeds the input (or a
    derived fragment of it), so allow-listing keys is the only form of this that stays safe
    as pydantic's error vocabulary grows.
    """
    safe: list[dict] = []
    for entry in errors:
        if not isinstance(entry, dict):  # pragma: no cover - defensive
            continue
        safe.append(
            {
                key: entry[key]
                for key in _SAFE_VALIDATION_ERROR_KEYS
                if key in entry
            }
        )
    return safe


async def _validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_body(
            "validation_error",
            "Request validation failed.",
            {"errors": _safe_validation_errors(exc.errors())},
        ),
    )


async def _unhandled_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    # Never leak the stack trace or internal exception text (Req 2.5). We emit a
    # generic message; the exception itself is available to server-side logging.
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_body(
            "internal_error",
            "An internal error occurred while processing the request.",
        ),
    )


async def _audit_unavailable_handler(_: Request, exc: Exception) -> JSONResponse:
    """Report an applied-but-unrecorded change distinctly (``audit_log_required``).

    503 with its own code rather than a generic 500, for two reasons a client can act on:
    the failure is upstream-and-transient (the audit store), and the mutation **was**
    applied — nothing spans the action's store and the audit store, so this is a refusal to
    acknowledge the change, not a rollback. A client that retried a generic 500 would create
    a duplicate; this tells it not to.
    """
    from agentforge.enterprise.audit import AuditUnavailableError

    assert isinstance(exc, AuditUnavailableError)
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=error_body(
            "audit_unavailable",
            "The change was applied but could not be recorded in the audit log, and this "
            "deployment requires every administrative change to be recorded. Do not retry; "
            "verify the current state and the audit store.",
            {"action": getattr(exc, "action", None), "applied": True},
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""
    from agentforge.enterprise.audit import AuditUnavailableError

    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(AuditUnavailableError, _audit_unavailable_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
