"""Usage_Sink implementations: ``Recording_Usage_Sink`` and ``NoOp_Usage_Sink``.

``Recording_Usage_Sink`` adapts the ``Usage_Recorder`` to the ``Usage_Sink`` seam;
``NoOp_Usage_Sink`` is the inert double for tests that do not assert on usage. Stubs
here; filled in a later task.
"""

from __future__ import annotations

from uuid import UUID

from agentforge.observability.models import Token_Count
from agentforge.observability.usage.base import Usage_Sink
from agentforge.observability.usage.recorder import Usage_Recorder


class Recording_Usage_Sink(Usage_Sink):
    """Adapts the Usage_Recorder to the Usage_Sink seam (stub)."""

    def __init__(self, recorder: Usage_Recorder) -> None:
        self._recorder = recorder

    def record(
        self,
        *,
        provider: str,
        model: str,
        tokens: Token_Count,
        org_id: UUID,
        user_id: UUID | None,
    ) -> None:
        """Forward the usage to the wrapped Usage_Recorder (which builds + persists it)."""
        self._recorder.record(
            provider=provider,
            model=model,
            tokens=tokens,
            org_id=org_id,
            user_id=user_id,
        )


class NoOp_Usage_Sink(Usage_Sink):
    """Inert Usage_Sink for tests that do not assert on usage."""

    def record(
        self,
        *,
        provider: str,
        model: str,
        tokens: Token_Count,
        org_id: UUID,
        user_id: UUID | None,
    ) -> None:
        return  # intentionally does nothing
