"""Typed request/response schemas (Pydantic) used by the API endpoints (Req 2.3).

Phase 1 defines the health and error schemas. Ingest/query/documents schemas are
included as typed models so every endpoint has a declared contract; the Phase 2
routers that use them are wired in later tasks.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


# --- error envelope ---
class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail


# --- health ---
class LivenessResponse(BaseModel):
    status: Literal["alive"] = "alive"


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    dependencies: dict[str, Literal["up", "down"]]


# --- ingest (contract for Phase 2 wiring) ---
class IngestResponse(BaseModel):
    document_id: str
    filename: str
    chunk_count: int
    status: Literal["ingested"]


# --- query (contract for Phase 2 wiring) ---
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=10)


class CitationModel(BaseModel):
    document_id: str
    chunk_id: str


class QueryResponse(BaseModel):
    answer: str
    grounded: bool
    provider: str
    citations: list[CitationModel] = Field(default_factory=list)


# --- documents (contract for Phase 2 wiring) ---
class DocumentSummary(BaseModel):
    document_id: str
    filename: str
    content_type: str
    size_bytes: int
    status: str
    chunk_count: int
    created_at: str
