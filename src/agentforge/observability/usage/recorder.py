"""Usage_Recorder: builds a Usage_Record (computing Cost) and persists it.

The recorder computes the ``cost`` via the ``Cost_Model`` and persists the built
``Usage_Record`` scoped to ``org_id`` through the ``Usage_Store`` (Req 2.2, 2.3). Stub
here; the build/persist logic is filled in a later task.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from agentforge.observability.cost import Cost_Model
from agentforge.observability.models import Token_Count, Usage_Record
from agentforge.observability.usage.base import Usage_Store


class Usage_Recorder:
    """Constructs and persists Usage_Records via the Cost_Model + Usage_Store."""

    def __init__(self, store: Usage_Store, cost_model: Cost_Model) -> None:
        self._store = store
        self._cost_model = cost_model

    def record(
        self,
        *,
        provider: str,
        model: str,
        tokens: Token_Count,
        org_id: UUID,
        user_id: UUID | None,
    ) -> Usage_Record:
        """Build a Usage_Record (cost via the Cost_Model) and persist it (Req 2.2, 2.3)."""
        cost = self._cost_model.cost_for(provider, model, tokens)  # (Req 2.2)
        record = Usage_Record(
            id=uuid4(),
            org_id=org_id,
            user_id=user_id,
            provider=provider,
            model=model,
            prompt_tokens=tokens.prompt,
            completion_tokens=tokens.completion,
            total_tokens=tokens.total,  # == prompt + completion (Req 2.7)
            cost=cost,
            created_at=datetime.now(timezone.utc),
        )
        return self._store.add(record)  # persisted scoped to org_id (Req 2.3)
