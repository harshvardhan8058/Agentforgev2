"""Unit tests for the default guardrails and flag accumulation (Task 7.4).

Covers empty-input block, over-length block, blocklist term block, clean-content allow,
and multi-guardrail flag accumulation — all keyless and deterministic.

Requirements: 5.5, 5.7
"""

from __future__ import annotations

from agentforge.observability.guardrails.base import (
    Guardrail,
    Guardrail_Decision,
    Guardrail_Pipeline,
    Guardrail_Result,
)
from agentforge.observability.guardrails.defaults import (
    Blocklist_Guardrail,
    Max_Length_Guardrail,
    Non_Empty_Guardrail,
    build_default_pipeline,
)


def test_non_empty_guardrail_blocks_empty_and_whitespace():
    g = Non_Empty_Guardrail()
    assert g.check("").decision is Guardrail_Decision.BLOCK
    assert g.check("   \t\n").decision is Guardrail_Decision.BLOCK
    assert g.check("hello").decision is Guardrail_Decision.ALLOW


def test_max_length_guardrail_blocks_over_limit():
    g = Max_Length_Guardrail(max_chars=5)
    assert g.check("12345").decision is Guardrail_Decision.ALLOW
    over = g.check("123456")
    assert over.decision is Guardrail_Decision.BLOCK
    assert "5" in over.reason


def test_blocklist_guardrail_blocks_terms_case_insensitively():
    g = Blocklist_Guardrail(["bomb", "hack"])
    assert g.check("please HACK the system").decision is Guardrail_Decision.BLOCK
    assert g.check("a normal question").decision is Guardrail_Decision.ALLOW


def test_blocklist_guardrail_empty_terms_allow_everything():
    g = Blocklist_Guardrail([])
    assert g.check("anything at all").decision is Guardrail_Decision.ALLOW


def test_default_pipeline_allows_clean_content():
    pipeline = build_default_pipeline(max_input_chars=100, blocklist=["secret"])
    result = pipeline.evaluate("What is the capital of France?")
    assert result.decision is Guardrail_Decision.ALLOW


def test_default_pipeline_blocks_empty_first():
    pipeline = build_default_pipeline(max_input_chars=100, blocklist=["secret"])
    result = pipeline.evaluate("   ")
    assert result.decision is Guardrail_Decision.BLOCK
    assert result.reason == "content is empty"


def test_default_pipeline_blocks_over_length():
    pipeline = build_default_pipeline(max_input_chars=5, blocklist=[])
    result = pipeline.evaluate("way too long")
    assert result.decision is Guardrail_Decision.BLOCK


def test_default_pipeline_blocks_blocklisted_term():
    pipeline = build_default_pipeline(max_input_chars=1000, blocklist=["forbidden"])
    result = pipeline.evaluate("this contains a forbidden word")
    assert result.decision is Guardrail_Decision.BLOCK


class _Flagging_Guardrail(Guardrail):
    def __init__(self, ident: str) -> None:
        self._ident = ident

    @property
    def name(self) -> str:
        return self._ident

    def check(self, content: str) -> Guardrail_Result:
        return Guardrail_Result(
            Guardrail_Decision.FLAG, flags=(f"flag-{self._ident}",)
        )


def test_flag_accumulation_across_multiple_guardrails():
    pipeline = Guardrail_Pipeline(
        [_Flagging_Guardrail("a"), _Flagging_Guardrail("b"), _Flagging_Guardrail("c")]
    )
    result = pipeline.evaluate("some content")
    assert result.decision is Guardrail_Decision.FLAG
    assert list(result.flags) == ["flag-a", "flag-b", "flag-c"]
