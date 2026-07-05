"""Guardrail seam: ``Guardrail`` (ABC), ``Guardrail_Decision``, ``Guardrail_Result``.

A ``Guardrail`` returns a ``Guardrail_Result`` of allow / flag / block for a piece of
content. The ``Guardrail_Pipeline`` runs its guardrails in a stable configured order,
accumulates flags, and short-circuits on the first block (Req 5.1, 5.2, 5.3, 5.5). The
default guardrails are pure functions of the content (Req 5.7). ``apply_input_guardrail``
is the reusable helper the query/agent/multi-agent entry points use to run the input
pipeline before invoking the downstream LLM/agent/multi-agent orchestrator: a ``BLOCK``
raises ``AppError("guardrail_blocked", 400, {"reason": ...})`` and the downstream is never
invoked (Req 5.4, 5.6).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import TypeVar

from fastapi import status

from agentforge.api.errors import AppError

T = TypeVar("T")


class Guardrail_Decision(str, Enum):
    """The outcome of a single Guardrail or the whole pipeline."""

    ALLOW = "allow"
    FLAG = "flag"
    BLOCK = "block"


@dataclass(frozen=True)
class Guardrail_Result:
    """The result of evaluating a Guardrail or the Guardrail_Pipeline."""

    decision: Guardrail_Decision
    flags: tuple[str, ...] = ()  # accumulated annotations (flag case)
    reason: str | None = None  # blocking reason (block case)


class Guardrail(ABC):
    """Abstract contract for a single input/output validation rule."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for this guardrail."""
        raise NotImplementedError

    @abstractmethod
    def check(self, content: str) -> Guardrail_Result:
        """Evaluate ``content``; a pure function of it for the default guardrails (Req 5.7)."""
        raise NotImplementedError


class Guardrail_Pipeline:
    """Ordered collection of Guardrails; block short-circuits, flags accumulate.

    ``evaluate`` runs the guardrails in the stable configured order, returns ``BLOCK`` at
    the first blocking result (evaluating none after it), ``ALLOW`` carrying every
    accumulated flag when some flag and none block, and ``ALLOW`` when all allow
    (Req 5.1, 5.2, 5.3, 5.5).
    """

    def __init__(self, guardrails: Sequence[Guardrail]) -> None:
        self._guardrails = tuple(guardrails)  # stable, defined order (Req 5.1)

    @property
    def guardrails(self) -> tuple[Guardrail, ...]:
        """The guardrails in their stable configured order."""
        return self._guardrails

    def evaluate(self, content: str) -> Guardrail_Result:
        """Evaluate ``content`` against every guardrail in order (Req 5.1-5.5)."""
        flags: list[str] = []
        for guardrail in self._guardrails:  # stable configured order (Req 5.1)
            result = guardrail.check(content)
            if result.decision is Guardrail_Decision.BLOCK:
                # Short-circuit: return the block reason and evaluate nothing after it
                # (Req 5.3).
                return Guardrail_Result(
                    Guardrail_Decision.BLOCK, reason=result.reason
                )
            if result.decision is Guardrail_Decision.FLAG:
                flags.extend(result.flags)  # accumulate (Req 5.5)
        if flags:
            # Some flagged, none blocked: allow but carry every accumulated flag (Req 5.5).
            return Guardrail_Result(Guardrail_Decision.FLAG, flags=tuple(flags))
        return Guardrail_Result(Guardrail_Decision.ALLOW)  # all allowed (Req 5.2)


def apply_input_guardrail(
    pipeline: Guardrail_Pipeline,
    content: str,
    downstream: Callable[[], T],
) -> T:
    """Run the input ``pipeline`` on ``content`` before invoking ``downstream``.

    When the pipeline blocks, raise ``AppError("guardrail_blocked", 400, {"reason": ...})``
    and do **not** invoke ``downstream`` (Req 5.4). Otherwise invoke ``downstream`` and
    return its result; a flagging pipeline still proceeds (Req 5.5, 5.6).
    """
    result = pipeline.evaluate(content)
    if result.decision is Guardrail_Decision.BLOCK:
        raise AppError(
            "guardrail_blocked",
            "Input was blocked by a guardrail.",
            status.HTTP_400_BAD_REQUEST,
            {"reason": result.reason},
        )
    return downstream()
