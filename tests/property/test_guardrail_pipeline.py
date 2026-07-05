"""Property-based test for the Guardrail_Pipeline (Task 7.3).

Feature: agentforge-observability, Property 8: Guardrail pipeline order, short-circuit,
and downstream prevention. For any ordered sequence of guardrails and any content: the
pipeline evaluates guardrails in configured order; if every guardrail returns allow the
result is ALLOW; if at least one returns flag and none returns block the result is ALLOW
carrying all accumulated flags; if some guardrail returns block, the pipeline returns
BLOCK with that reason and evaluates no guardrail after the first block; the default
pipeline's result is a pure function of the content (identical across repeated calls); and
for any input that the input pipeline blocks at the query/agent/multi-agent entry point,
the downstream LLM_Provider/agent/multi-agent orchestrator is invoked zero times.

Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 11.6
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.api.errors import AppError
from agentforge.observability.guardrails.base import (
    Guardrail,
    Guardrail_Decision,
    Guardrail_Pipeline,
    Guardrail_Result,
    apply_input_guardrail,
)
from agentforge.observability.guardrails.defaults import build_default_pipeline


class _Recording_Guardrail(Guardrail):
    """A guardrail with a fixed decision that records every content it evaluates."""

    def __init__(self, ident: str, decision: Guardrail_Decision, log: list[str]) -> None:
        self._ident = ident
        self._decision = decision
        self._log = log

    @property
    def name(self) -> str:
        return self._ident

    def check(self, content: str) -> Guardrail_Result:
        self._log.append(self._ident)
        if self._decision is Guardrail_Decision.BLOCK:
            return Guardrail_Result(
                Guardrail_Decision.BLOCK, reason=f"blocked-by-{self._ident}"
            )
        if self._decision is Guardrail_Decision.FLAG:
            return Guardrail_Result(
                Guardrail_Decision.FLAG, flags=(f"flag-{self._ident}",)
            )
        return Guardrail_Result(Guardrail_Decision.ALLOW)


_decisions = st.sampled_from(
    [Guardrail_Decision.ALLOW, Guardrail_Decision.FLAG, Guardrail_Decision.BLOCK]
)


# Feature: agentforge-observability, Property 8: Guardrail pipeline order, short-circuit,
# and downstream prevention.
@hyp_settings(max_examples=200, deadline=None)
@given(
    decisions=st.lists(_decisions, min_size=0, max_size=8),
    content=st.text(max_size=50),
)
def test_guardrail_pipeline_order_shortcircuit_and_downstream(decisions, content):
    log: list[str] = []
    guardrails = [
        _Recording_Guardrail(f"g{i}", d, log) for i, d in enumerate(decisions)
    ]
    pipeline = Guardrail_Pipeline(guardrails)

    result = pipeline.evaluate(content)

    # Determine the first block position (if any) in configured order.
    first_block = next(
        (i for i, d in enumerate(decisions) if d is Guardrail_Decision.BLOCK), None
    )

    if first_block is not None:
        # BLOCK with that reason; nothing evaluated after the first block (Req 5.3).
        assert result.decision is Guardrail_Decision.BLOCK
        assert result.reason == f"blocked-by-g{first_block}"
        assert log == [f"g{i}" for i in range(first_block + 1)]
    else:
        # Evaluated every guardrail in order (Req 5.1).
        assert log == [f"g{i}" for i in range(len(decisions))]
        flagged = [
            f"flag-g{i}"
            for i, d in enumerate(decisions)
            if d is Guardrail_Decision.FLAG
        ]
        if flagged:
            # Some flag, none block -> allow with all accumulated flags (Req 5.5).
            assert result.decision is Guardrail_Decision.FLAG
            assert list(result.flags) == flagged
        else:
            # All allow -> ALLOW (Req 5.2).
            assert result.decision is Guardrail_Decision.ALLOW


# Feature: agentforge-observability, Property 8 (determinism clause): the default pipeline
# is a pure function of the content.
@hyp_settings(max_examples=100, deadline=None)
@given(content=st.text(max_size=200))
def test_default_pipeline_is_pure_function_of_content(content):
    pipeline = build_default_pipeline(max_input_chars=50, blocklist=["forbidden"])
    first = pipeline.evaluate(content)
    second = build_default_pipeline(
        max_input_chars=50, blocklist=["forbidden"]
    ).evaluate(content)
    assert first == second


# Feature: agentforge-observability, Property 8 (downstream-prevention clause): a blocking
# input invokes the downstream zero times.
@hyp_settings(max_examples=100, deadline=None)
@given(
    decisions=st.lists(_decisions, min_size=1, max_size=6),
    content=st.text(max_size=50),
)
def test_apply_input_guardrail_prevents_downstream_on_block(decisions, content):
    log: list[str] = []
    guardrails = [
        _Recording_Guardrail(f"g{i}", d, log) for i, d in enumerate(decisions)
    ]
    pipeline = Guardrail_Pipeline(guardrails)

    calls = {"count": 0}

    def downstream() -> str:
        calls["count"] += 1
        return "downstream-result"

    has_block = any(d is Guardrail_Decision.BLOCK for d in decisions)

    if has_block:
        with pytest.raises(AppError) as excinfo:
            apply_input_guardrail(pipeline, content, downstream)
        assert excinfo.value.code == "guardrail_blocked"
        assert excinfo.value.status_code == 400
        # Downstream invoked zero times (Req 5.4, 11.6).
        assert calls["count"] == 0
    else:
        assert apply_input_guardrail(pipeline, content, downstream) == "downstream-result"
        assert calls["count"] == 1
