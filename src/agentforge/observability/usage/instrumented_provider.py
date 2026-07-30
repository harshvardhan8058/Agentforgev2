"""Instrumented_Provider: a decorator over the LLM_Provider seam for usage capture.

``Instrumented_Provider`` implements ``LLM_Provider`` and wraps another ``LLM_Provider``,
emitting one usage record per ``generate`` call while delegating generation unchanged.
It exposes the wrapped provider's ``name``, delegates **first**, then emits inside a
guard that swallows any exception so the wrapped result is always returned unchanged
(Req 2.1, 7.1, 7.2, 7.7, 9.2).

The acting ``org_id`` / ``user_id`` are read from the request-scoped tenancy context
(``enterprise/tenancy``), so usage is attributed to the right tenant/user without widening
the ``LLM_Provider`` contract (Req 2.1, 2.3).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from agentforge.enterprise.tenancy import current_org, current_user
from agentforge.llm.base import GenerationResult, LLM_Provider
from agentforge.observability.models import Token_Count
from agentforge.observability.usage.base import Usage_Sink

_WHITESPACE = re.compile(r"\s+")


def _whitespace_token_count(text: str) -> int:
    """Return the number of whitespace-delimited tokens in ``text`` (pure function)."""
    stripped = text.strip()
    if not stripped:
        return 0
    return len(_WHITESPACE.split(stripped))


def deterministic_token_count(prompt: str, result: GenerationResult) -> Token_Count:
    """Return a Token_Count that is a pure function of the request/response text.

    Uses whitespace-delimited token counts of ``prompt`` (prompt tokens) and
    ``result.text`` (completion tokens), so with the deterministic Fallback_Provider the
    emitted usage is fully reproducible and ``total == prompt + completion`` by
    construction (Req 2.4, 2.7).
    """
    return Token_Count(
        prompt=_whitespace_token_count(prompt),
        completion=_whitespace_token_count(result.text),
    )


def _model_of(result: GenerationResult) -> str:
    """Return the model that served the call, falling back to the provider name.

    A provider that knows its model reports it on ``GenerationResult.model``; the
    fallback keeps the field populated for providers that cannot, since the usage
    record requires a model identifier. When every provider fell back, the "by
    model" analytics breakdown was an exact duplicate of "by provider".
    """
    return result.model or result.provider


class Instrumented_Provider(LLM_Provider):
    """LLM_Provider decorator that emits exactly one usage record per generate call.

    Delegation to the wrapped provider happens **first**; usage emission then runs inside
    a guard that swallows any exception, so a failing ``Usage_Sink`` can never change the
    returned ``GenerationResult`` (Req 7.2, 7.7).
    """

    def __init__(
        self,
        wrapped: LLM_Provider,
        sink: Usage_Sink,
        *,
        token_counter: Callable[[str, GenerationResult], Token_Count] | None = None,
    ) -> None:
        self._wrapped = wrapped
        self._sink = sink
        self._count = token_counter or deterministic_token_count

    @property
    def name(self) -> str:
        return self._wrapped.name  # identity is transparent to callers (Req 7.1)

    def generate(self, prompt: str) -> GenerationResult:
        result = self._wrapped.generate(prompt)  # delegate FIRST (Req 7.2)
        try:
            tokens = self._count(prompt, result)  # pure fn of the request (Req 2.4)
            self._sink.record(
                provider=result.provider,
                model=_model_of(result),
                tokens=tokens,
                org_id=current_org(),
                user_id=current_user(),
            )
        except Exception:  # noqa: BLE001 - usage capture must not change the result
            pass  # (Req 7.7)
        return result
