"""Ingest router: ``POST /documents`` (multipart upload) — Task 13.1.

Accepts a ``multipart/form-data`` file upload, hands the raw bytes to the
Ingestion_Service, and returns ``201`` with the document id, filename, chunk count, and
status on success. Every rejection is mapped to the design's error envelope with the
correct HTTP status and stable error code:

* empty / no-text document -> ``400 empty_document``
* unsupported format       -> ``415 unsupported_format``
* extraction failure       -> ``422 extraction_failure``
* extraction timeout       -> ``422 extraction_timeout``
* oversized document       -> ``413 size_limit_exceeded``
* embedding failure         -> ``500 embedding_error``

The synchronous ingestion pipeline runs in a worker thread so it never blocks the event
loop.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_ingestion_service, require_permission
from agentforge.api.errors import AppError
from agentforge.api.schemas import IngestResponse
from agentforge.enterprise.models import Principal
from agentforge.enterprise.rbac import Permission
from agentforge.embeddings.base import EmbeddingError
from agentforge.ingestion.extractors import SUPPORTED_CONTENT_TYPES
from agentforge.ingestion.service import (
    EmptyDocumentError,
    ExtractionTimeoutError,
    Ingestion_Service,
    SizeLimitError,
    UnsupportedFormatError,
)
from agentforge.ingestion.extractors import ExtractionError

router = APIRouter(tags=["documents"])


def _resolve_content_type(filename: str, declared: str | None) -> str:
    """Resolve the effective content type.

    Prefer an explicitly declared supported content type; otherwise infer from the
    filename extension (browsers often send ``application/octet-stream`` for ``.md`` /
    ``.txt`` uploads). Unknown types are passed through so the service rejects them with
    ``415 unsupported_format``.
    """
    if declared in SUPPORTED_CONTENT_TYPES:
        return declared
    lower = (filename or "").lower()
    if lower.endswith((".md", ".markdown")):
        return "text/markdown"
    if lower.endswith(".pdf"):
        return "application/pdf"
    if lower.endswith((".txt", ".text")):
        return "text/plain"
    return declared or "application/octet-stream"


@router.post(
    "/documents",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    filename: str | None = Form(default=None),
    service: Ingestion_Service = Depends(get_ingestion_service),
    principal: Principal = Depends(require_permission(Permission.INGEST_DOCUMENTS)),
) -> IngestResponse:
    """Ingest an uploaded document into the caller's org and return its summary (Req 7.3)."""
    effective_filename = filename or file.filename or "upload"
    content_type = _resolve_content_type(effective_filename, file.content_type)
    data = await file.read()

    try:
        result = await run_in_threadpool(
            lambda: service.ingest(
                effective_filename, content_type, data, org_id=principal.org_id
            )
        )
    except SizeLimitError as exc:
        raise AppError(
            "size_limit_exceeded", str(exc), status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
        ) from exc
    except UnsupportedFormatError as exc:
        raise AppError(
            "unsupported_format", str(exc), status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
        ) from exc
    except EmptyDocumentError as exc:
        raise AppError(
            "empty_document", str(exc), status.HTTP_400_BAD_REQUEST
        ) from exc
    except ExtractionTimeoutError as exc:
        raise AppError(
            "extraction_timeout", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    except ExtractionError as exc:
        raise AppError(
            "extraction_failure", str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    except EmbeddingError as exc:
        raise AppError(
            "embedding_error", str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR
        ) from exc

    return IngestResponse(
        document_id=result.document_id,
        filename=result.filename,
        chunk_count=result.chunk_count,
        status="ingested",
    )
