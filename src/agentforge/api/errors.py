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


# --- work that must still happen when the response is an error --------------------

# FastAPI's ``BackgroundTasks`` are attached to the response an endpoint *returns*, so an
# endpoint that raises loses them. Some follow-up work is owed regardless of the status: a
# guardrail block is a real, reportable security event, and the subscribers who need to hear
# about it must not be dropped merely because the caller's request ended in a 400.
#
# Deliberately narrow: only :class:`AppError` (a *handled* domain outcome) carries deferred
# work. An unhandled exception means the process is in an unknown state and is no place to be
# running further side effects.
_DEFERRED_ATTR = "deferred_error_tasks"


def defer_after_error(request: Request, task: Callable[[], None]) -> None:
    """Run ``task`` after this request's error response has been sent.

    Registered on the request, not the response, because the caller is about to raise. Only
    honoured for :class:`AppError`; a task registered on a request that then succeeds is simply
    never run, which is why callers register it immediately before raising.
    """
    tasks: list[Callable[[], None]] = getattr(request.state, _DEFERRED_ATTR, [])
    tasks.append(task)
    setattr(request.state, _DEFERRED_ATTR, tasks)


def _run_deferred(tasks: list[Callable[[], None]]) -> None:
    """Run every deferred task, isolating failures: one must not cancel the others."""
    for task in tasks:
        try:
            task()
        except Exception:  # noqa: BLE001 - post-response work cannot affect the response
            logger.warning("A deferred post-error task failed.", exc_info=True)


async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    tasks: list[Callable[[], None]] = getattr(request.state, _DEFERRED_ATTR, [])
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.details),
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
