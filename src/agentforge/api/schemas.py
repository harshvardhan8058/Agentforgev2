"""Typed request/response schemas (Pydantic) used by the API endpoints (Req 2.3).

Phase 1 defines the health and error schemas. Ingest/query/documents schemas are
included as typed models so every endpoint has a declared contract; the Phase 2
routers that use them are wired in later tasks.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from agentforge.enterprise.rbac import Role as RbacRole


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
    # Phase 6: output-guardrail annotations attached without blocking (Req 5.5, 5.6).
    flags: list[str] = Field(default_factory=list)


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
    # Phase 6: output-guardrail annotations attached without blocking (Req 5.5, 5.6).
    flags: list[str] = Field(default_factory=list)


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
    # Phase 6: output-guardrail annotations attached without blocking (Req 5.5, 5.6).
    flags: list[str] = Field(default_factory=list)


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



# --- enterprise: authentication (Phase 5) -----------------------------------------


class RegisterSelfRequest(BaseModel):
    """Self-registration body: bootstraps a new Organization + owner User (Req 1.1)."""

    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    org_name: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    """Login body: verifies credentials to issue an Access_Token (Req 1.2, 1.3)."""

    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """A freshly-issued bearer Access_Token (Req 1.2)."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"


# --- enterprise: organizations, members, teams (Phase 5) --------------------------


class CreateOrgRequest(BaseModel):
    """Body for ``POST /orgs`` — an authenticated user creates an org they own."""

    name: str = Field(..., min_length=1)


class CreateOrgResponse(BaseModel):
    """Response carrying the newly-created Org_Id (Req 2.1)."""

    org_id: UUID


class AddMemberRequest(BaseModel):
    """Body for ``POST /orgs/{id}/members`` — add an existing user under a Role (Req 2.2)."""

    email: str = Field(..., min_length=1)
    role: RbacRole


class AddMemberResponse(BaseModel):
    """Response describing the persisted Membership (Req 2.2)."""

    user_id: UUID
    org_id: UUID
    role: RbacRole


class CreateTeamRequest(BaseModel):
    """Body for ``POST /orgs/{id}/teams`` — create an org-scoped Team (Req 2.3)."""

    name: str = Field(..., min_length=1)


class CreateTeamResponse(BaseModel):
    """Response carrying the newly-created Team id (Req 2.3)."""

    team_id: UUID
    name: str


class AddTeamMemberRequest(BaseModel):
    """Body for ``POST /orgs/{id}/teams/{tid}/members`` — add a user by email (Req 2.4)."""

    email: str = Field(..., min_length=1)


class AddTeamMemberResponse(BaseModel):
    """Response describing the persisted Team_Membership (Req 2.4)."""

    team_id: UUID
    user_id: UUID


# --- enterprise: API keys (Phase 5) -----------------------------------------------


class CreateApiKeyRequest(BaseModel):
    """Body for ``POST /orgs/{id}/api-keys`` — issue a key granting ``role`` (Req 5.1)."""

    role: RbacRole


class CreateApiKeyResponse(BaseModel):
    """Creation response carrying the plaintext secret **exactly once** (Req 5.1, 5.2)."""

    api_key_id: UUID
    secret: str
    role: RbacRole
    key_prefix: str


class ApiKeyMetadata(BaseModel):
    """Safe API-key metadata — never the ``key_hash`` or the plaintext secret (Req 5.4)."""

    id: UUID
    org_id: UUID
    role: RbacRole
    key_prefix: str
    revoked_at: datetime | None = None
    created_at: datetime



# --- observability: analytics / cost (Phase 6) ------------------------------------


class UsageBreakdownEntry(BaseModel):
    """One grouped row of a usage breakdown (by provider / model / user) (Req 3.2)."""

    key: str
    total_tokens: int
    # Exact monetary total rendered as a string so no float drift crosses the wire.
    total_cost: str


class UsageReportResponse(BaseModel):
    """Aggregated usage + cost for the caller's org over a time range (Req 3.1, 3.4)."""

    org_id: UUID
    start: datetime
    end: datetime
    total_tokens: int
    total_cost: str
    by_provider: list[UsageBreakdownEntry] = Field(default_factory=list)
    by_model: list[UsageBreakdownEntry] = Field(default_factory=list)
    by_user: list[UsageBreakdownEntry] = Field(default_factory=list)


# --- observability: prompt registry (Phase 6) -------------------------------------


class CreatePromptVersionRequest(BaseModel):
    """Body for ``POST /prompts`` — append a new immutable Prompt_Version (Req 4.1)."""

    name: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    variables: list[str] = Field(default_factory=list)


class PromptVersionResponse(BaseModel):
    """A resolved Prompt_Version (latest or a specific number) (Req 4.3, 4.4)."""

    id: UUID
    name: str
    version: int
    body: str
    variables: list[str] = Field(default_factory=list)
    created_at: datetime


class RenderPromptRequest(BaseModel):
    """Body for ``POST /prompts/{name}/render`` — supply the variable values (Req 4.6)."""

    variables: dict[str, str] = Field(default_factory=dict)
    version: int | None = None


class RenderPromptResponse(BaseModel):
    """The rendered prompt string for a resolved version (Req 4.6)."""

    name: str
    version: int
    rendered: str


# --- observability: guardrails (Phase 6) ------------------------------------------


class GuardrailInfo(BaseModel):
    """An active guardrail's stable name and kind (Req 5.1)."""

    name: str
    kind: str


class GuardrailConfigResponse(BaseModel):
    """The ordered list of active guardrails (names + kinds) (Req 5.1)."""

    guardrails: list[GuardrailInfo] = Field(default_factory=list)


class GuardrailEvaluateRequest(BaseModel):
    """Body for ``POST /guardrails/evaluate`` — content to run through the pipeline."""

    content: str = ""


class GuardrailEvaluateResponse(BaseModel):
    """The pipeline's allow / flag / block decision with flags/reason (Req 5.2-5.5)."""

    decision: Literal["allow", "flag", "block"]
    flags: list[str] = Field(default_factory=list)
    reason: str | None = None


# --- observability: evaluation framework (Phase 6) --------------------------------


class EvaluationItemRequest(BaseModel):
    """One dataset item: an input and an optional expected output (Req 6.1)."""

    input: str = Field(..., min_length=1)
    expected: str | None = None


class CreateDatasetRequest(BaseModel):
    """Body for ``POST /evaluations/datasets`` — a named dataset + its items (Req 6.1)."""

    name: str = Field(..., min_length=1)
    items: list[EvaluationItemRequest] = Field(default_factory=list)


class CreateDatasetResponse(BaseModel):
    """Response carrying the newly-created Evaluation_Dataset id (Req 6.1)."""

    dataset_id: UUID
    name: str


class DatasetSummary(BaseModel):
    """Safe metadata for one Evaluation_Dataset in the org's list (Req 6.5)."""

    dataset_id: UUID
    name: str
    created_at: datetime


class EvaluationRunRequest(BaseModel):
    """Body for ``POST /evaluations/runs`` — run named evaluators over a dataset (Req 6.2)."""

    dataset_id: UUID
    evaluators: list[str] = Field(..., min_length=1)


class EvaluationItemScore(BaseModel):
    """The score one Evaluator assigned to one item within a run (Req 6.9)."""

    item_id: UUID
    evaluator: str
    score: float


class EvaluationRunResponse(BaseModel):
    """A persisted Evaluation_Run: aggregate + per-item scores (Req 6.9)."""

    run_id: UUID
    dataset_id: UUID
    aggregate_score: float
    results: list[EvaluationItemScore] = Field(default_factory=list)


# --- integrations: status introspection (Phase 8) ---------------------------------


class IntegrationStatusEntry(BaseModel):
    """One integration's public status: its stable name and whether it is Enabled.

    Contains only ``{name, enabled}`` — never a credential, token, or secret-derived
    field (Req 9.2, 9.5).
    """

    name: str
    enabled: bool


class IntegrationStatusResponse(BaseModel):
    """The org-scoped Integration_Status view: one ``{name, enabled}`` entry per integration.

    No credential, token, or secret-derived field appears anywhere in the response (Req 9.2).
    """

    integrations: list[IntegrationStatusEntry] = Field(default_factory=list)
