"""Uniform error envelope and FastAPI exception handlers.

All error responses share the envelope ``{ "error": { code, message, details } }``.
Unknown routes return 404 ``not_found`` (Req 2.2) and unhandled exceptions return
500 ``internal_error`` without leaking a stack trace (Req 2.5).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


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


async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(exc.code, exc.message, exc.details),
    )


async def _http_exception_handler(
    _: Request, exc: StarletteHTTPException
) -> JSONResponse:
    code = _STATUS_CODE_NAMES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"
    return JSONResponse(status_code=exc.status_code, content=error_body(code, message))


async def _validation_exception_handler(
    _: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_body(
            "validation_error",
            "Request validation failed.",
            {"errors": exc.errors()},
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


def register_exception_handlers(app: FastAPI) -> None:
    """Register all exception handlers on the FastAPI app."""
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)
