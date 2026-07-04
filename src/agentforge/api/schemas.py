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


# --- conversations (Phase 3) ---
Role = Literal["user", "assistant", "tool", "system"]


class CreateConversationResponse(BaseModel):
    conversation_id: str


class AppendMessageRequest(BaseModel):
    role: Role
    content: str = Field(..., min_length=1)


class MessageModel(BaseModel):
    role: str
    content: str
    position: int


class ConversationHistoryResponse(BaseModel):
    conversation_id: str
    messages: list[MessageModel] = Field(default_factory=list)


# --- agent (Phase 3) ---
class AgentRunRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str | None = None


class AgentRunResponse(BaseModel):
    run_id: str
    conversation_id: str
    answer: str
    termination_reason: Literal["final-answer", "iteration-limit-reached"]
    citations: list[CitationModel] = Field(default_factory=list)


class TraceEntryModel(BaseModel):
    ordinal: int
    step_type: str
    role_id: str | None = None  # Phase 4: attributes multi-agent role steps (Req 6.1)
    tool_name: str | None = None
    outcome: str | None = None


class TraceResponse(BaseModel):
    run_id: str
    entries: list[TraceEntryModel] = Field(default_factory=list)



# --- multi-agent (Phase 4) --------------------------------------------------------

MultiAgentRunStatus = Literal["running", "awaiting_approval", "terminated"]

TerminationReasonName = Literal[
    "completed",
    "max-rounds-reached",
    "max-revisions-reached",
    "rejected",
    "aborted",
]


class StartMultiAgentRunRequest(BaseModel):
    """Request body for starting a Multi_Agent_Run (Req 9.1)."""

    task: str = Field(..., min_length=1)
    conversation_id: str | None = None


class StartMultiAgentRunResponse(BaseModel):
    """Response for :class:`StartMultiAgentRunRequest` (Req 9.1)."""

    run_id: str
    conversation_id: str
    status: MultiAgentRunStatus


ApprovalDecisionKind = Literal["approve", "reject", "edit"]


class ApprovalDecisionRequest(BaseModel):
    """Body for :func:`submit_approval` — a human decision on a paused run (Req 9.3)."""

    type: ApprovalDecisionKind
    feedback: str | None = None
    edited_content: str | None = None


class ApprovalDecisionResponse(BaseModel):
    """Response after applying an Approval_Decision to a paused run (Req 9.3)."""

    run_id: str
    status: MultiAgentRunStatus
    termination_reason: TerminationReasonName | None = None


class FinalOutputModel(BaseModel):
    """The Final_Output emitted when a Multi_Agent_Run terminates successfully."""

    content: str
    citations: list[CitationModel] = Field(default_factory=list)


class MultiAgentRunResult(BaseModel):
    """Full run result: status, termination reason, final output, and trace (Req 9.4)."""

    run_id: str
    status: MultiAgentRunStatus
    termination_reason: TerminationReasonName | None = None
    final_output: FinalOutputModel | None = None
    trace: list[TraceEntryModel] = Field(default_factory=list)
