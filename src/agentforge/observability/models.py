"""Observability domain models: plain, framework-agnostic dataclasses.

Consistent with the Phase 3-5 domain models. **No model holds a secret**; the monetary
``Cost`` uses :class:`~decimal.Decimal` for exact arithmetic (never a float), and every
persisted record carries an ``org_id`` so tenant scoping is enforceable at the
data-access layer (Req 2.7, 8.2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class Token_Count:
    """The prompt/completion token quantities for a single LLM_Provider call.

    The ``total`` is derived, so the invariant ``total == prompt + completion`` holds by
    construction and can never drift (Req 2.7).
    """

    prompt: int
    completion: int

    @property
    def total(self) -> int:
        """Total tokens; always equal to ``prompt + completion`` (Req 2.7)."""
        return self.prompt + self.completion


@dataclass
class Usage_Record:
    """A persisted record of a single LLM_Provider call (Req 2.1, 2.2, 2.3)."""

    id: UUID
    org_id: UUID  # FK -> organizations(id); tenant scope key (Req 8.2)
    user_id: UUID | None  # attribution; None for unattributed calls (Req 2.1)
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int  # == prompt_tokens + completion_tokens (Req 2.7)
    cost: Decimal  # computed by the Cost_Model (Req 2.2)
    created_at: datetime


@dataclass
class Breakdown_Entry:
    """One grouped row of a Usage_Report breakdown (by provider / model / user)."""

    key: str  # provider name / model name / user_id rendered as a string
    total_tokens: int
    total_cost: Decimal


@dataclass
class Usage_Report:
    """Aggregated usage + cost for an Organization over a time range (Req 3.1, 3.2)."""

    org_id: UUID
    start: datetime
    end: datetime
    total_tokens: int
    total_cost: Decimal
    by_provider: list[Breakdown_Entry]
    by_model: list[Breakdown_Entry]
    by_user: list[Breakdown_Entry]


@dataclass
class Prompt_Template:
    """A named, org-scoped prompt owning an ordered sequence of Prompt_Versions."""

    id: UUID
    org_id: UUID  # FK -> organizations(id) (Req 8.2)
    name: str  # UNIQUE (org_id, name)
    created_at: datetime


@dataclass(frozen=True)
class Prompt_Version:
    """An immutable revision of a Prompt_Template (Req 4.1, 4.2, 4.9).

    Frozen so a persisted version's ``body`` / ``variables`` can never be mutated in
    process; ``version`` is monotonic and contiguous from 1 per ``(org_id, name)``.
    """

    id: UUID
    org_id: UUID  # FK -> organizations(id) (Req 8.2)
    template_name: str
    version: int  # monotonic, contiguous from 1 (Req 4.1, 4.9)
    body: str  # immutable (Req 4.2)
    variables: tuple[str, ...]  # declared variable names (immutable)
    created_at: datetime


@dataclass
class Evaluation_Dataset:
    """An org-scoped named collection of Evaluation_Items (Req 6.1)."""

    id: UUID
    org_id: UUID  # FK -> organizations(id) (Req 8.2)
    name: str
    created_at: datetime


@dataclass
class Evaluation_Item:
    """One entry in an Evaluation_Dataset: an input and an optional expected output."""

    id: UUID
    dataset_id: UUID  # FK -> evaluation_datasets(id) (Req 8.3)
    org_id: UUID
    input: str
    expected: str | None


@dataclass
class Evaluation_Result:
    """The score an Evaluator assigned to a single Evaluation_Item within a run."""

    item_id: UUID  # FK -> evaluation_items(id)
    evaluator: str
    score: float


@dataclass
class Evaluation_Run:
    """The persisted, org-scoped result of an Evaluation_Run (Req 6.5, 6.9)."""

    id: UUID
    org_id: UUID  # FK -> organizations(id) (Req 8.2)
    dataset_id: UUID  # FK -> evaluation_datasets(id)
    aggregate_score: float  # == aggregation of per-item scores (Req 6.9)
    results: list[Evaluation_Result] = field(default_factory=list)
    created_at: datetime | None = None
