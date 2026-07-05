"""Deterministic default guardrails (Req 5.7, 10.2).

Non-empty, max-input-length (from ``guardrail_max_input_chars``), and static blocklist
(from ``guardrail_blocklist_json``) guardrails whose ``check(content)`` is a pure function
of the content, plus the default pipeline factory used by the composition root. Because
each check depends only on ``content`` (and the guardrail's fixed configuration), the
default pipeline's result is fully reproducible on the keyless path (Req 5.7, 10.2).
"""

from __future__ import annotations

from collections.abc import Sequence

from agentforge.observability.guardrails.base import (
    Guardrail,
    Guardrail_Decision,
    Guardrail_Pipeline,
    Guardrail_Result,
)


class Non_Empty_Guardrail(Guardrail):
    """Blocks empty / whitespace-only content."""

    @property
    def name(self) -> str:
        return "non_empty"

    def check(self, content: str) -> Guardrail_Result:
        """Block iff ``content`` is empty or only whitespace (pure fn of content)."""
        if content.strip() == "":
            return Guardrail_Result(
                Guardrail_Decision.BLOCK, reason="content is empty"
            )
        return Guardrail_Result(Guardrail_Decision.ALLOW)


class Max_Length_Guardrail(Guardrail):
    """Blocks content longer than a configured maximum number of characters."""

    def __init__(self, max_chars: int) -> None:
        self._max_chars = max_chars

    @property
    def name(self) -> str:
        return "max_length"

    def check(self, content: str) -> Guardrail_Result:
        """Block iff ``len(content) > max_chars`` (pure fn of content)."""
        if len(content) > self._max_chars:
            return Guardrail_Result(
                Guardrail_Decision.BLOCK,
                reason=f"content exceeds {self._max_chars} characters",
            )
        return Guardrail_Result(Guardrail_Decision.ALLOW)


class Blocklist_Guardrail(Guardrail):
    """Blocks content containing any configured blocklist term (case-insensitive)."""

    def __init__(self, terms: Sequence[str]) -> None:
        # Normalise to lower-case, dropping empty terms, so matching is deterministic.
        self._terms = tuple(t.lower() for t in terms if t)

    @property
    def name(self) -> str:
        return "blocklist"

    def check(self, content: str) -> Guardrail_Result:
        """Block iff any configured term appears in ``content`` (pure fn of content)."""
        lowered = content.lower()
        for term in self._terms:
            if term in lowered:
                return Guardrail_Result(
                    Guardrail_Decision.BLOCK,
                    reason=f"content contains a blocked term: {term!r}",
                )
        return Guardrail_Result(Guardrail_Decision.ALLOW)


def build_default_pipeline(
    *, max_input_chars: int = 8000, blocklist: Sequence[str] | None = None
) -> Guardrail_Pipeline:
    """Return the default deterministic Guardrail_Pipeline in a stable order.

    Order: non-empty check, then max-length, then the static blocklist. The composition
    root supplies ``max_input_chars`` from ``guardrail_max_input_chars`` and ``blocklist``
    from ``guardrail_blocklist_json`` (Req 5.7, 10.2).
    """
    return Guardrail_Pipeline(
        [
            Non_Empty_Guardrail(),
            Max_Length_Guardrail(max_input_chars),
            Blocklist_Guardrail(blocklist or ()),
        ]
    )
