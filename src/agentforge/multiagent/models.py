"""Multi-agent domain models (Phase 4).

Plain, framework-agnostic dataclasses consistent with ``models/domain.py`` — they depend
on neither FastAPI nor LangGraph so the multi-agent core stays decoupled from transport
and orchestration infrastructure. The existing :class:`Citation` type is **reused**
unchanged (Req 8): findings, drafts, and the final output all carry ``Citation`` objects
produced by the existing RAG pipeline rather than a redefined citation type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Citation is REUSED from the Phase 1-2 domain models, never redefined (Req 8).
from agentforge.models.domain import Citation


@dataclass
class Plan:
    """The ordered set of steps produced by the Planner_Agent for the task (Req 4.3)."""

    steps: list[str] = field(default_factory=list)


@dataclass
class Research_Finding:
    """One gathered piece of grounded information with its supporting Citations."""

    content: str
    citations: list[Citation] = field(default_factory=list)  # Req 4.4, 8.1


@dataclass
class Research_Findings:
    """The gathered information produced by the Researcher_Agent (Req 4.4, 8.1)."""

    findings: list[Research_Finding] = field(default_factory=list)

    def all_citations(self) -> list[Citation]:
        """Flatten the Citations across every finding, preserving order."""
        return [citation for finding in self.findings for citation in finding.citations]


@dataclass
class Draft:
    """The current candidate output produced or revised by the Writer_Agent.

    ``citations`` are the Citations of the Research_Findings content the draft draws on,
    preserved unchanged across revision cycles (Req 8.2).
    """

    content: str
    citations: list[Citation] = field(default_factory=list)


@dataclass
class Critic_Feedback:
    """The structured review produced by the Critic_Agent (Req 4.6).

    ``revision_required`` is the explicit flag the orchestrator routes on: ``True`` sends
    the draft back to the Writer (bounded by Max_Revisions), ``False`` approves it.
    """

    revision_required: bool
    comments: str = ""


class ApprovalDecisionType(str, Enum):
    """The type of a human Approval_Decision (Req 5.2-5.4)."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"


@dataclass
class Approval_Decision:
    """A human decision submitted for a paused Multi_Agent_Run."""

    type: ApprovalDecisionType
    feedback: str | None = None  # carried on reject (Req 5.3)
    edited_content: str | None = None  # carried on edit (Req 5.4)


@dataclass
class Final_Output:
    """The task result emitted when a Multi_Agent_Run terminates successfully.

    ``citations`` are carried from the approved Draft so the collaborative result stays
    grounded and verifiable (Req 8.3).
    """

    content: str
    citations: list[Citation] = field(default_factory=list)


class Termination_Reason(str, Enum):
    """The single explicit reason a Multi_Agent_Run ends with (Req 2.7)."""

    COMPLETED = "completed"
    MAX_ROUNDS_REACHED = "max-rounds-reached"
    MAX_REVISIONS_REACHED = "max-revisions-reached"
    REJECTED = "rejected"
    ABORTED = "aborted"


@dataclass
class Multi_Agent_Run:
    """A single invocation of the Multi_Agent_Orchestrator for one task (Req 10.1)."""

    id: str
    conversation_id: str
    task: str
    # running | awaiting_approval | terminated
    status: str = "running"
    termination_reason: Termination_Reason | None = None
    final_output: Final_Output | None = None
