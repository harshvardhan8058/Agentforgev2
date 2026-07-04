"""Unit tests for the multi-agent domain models and Blackboard_State (Task 2.5).

Cover ``Research_Findings.all_citations()`` flattening, default empty citation lists, and
the zero-initialized Blackboard_State counters (Req 4.1, 4.7).
"""

from __future__ import annotations

from agentforge.models.domain import Citation
from agentforge.multiagent.models import (
    Draft,
    Research_Finding,
    Research_Findings,
    Termination_Reason,
)
from agentforge.multiagent.state import (
    DEFAULT_MAX_REVISIONS,
    DEFAULT_MAX_ROUNDS,
    Blackboard_State,
)


def test_all_citations_flattens_in_order():
    """all_citations() flattens every finding's citations preserving order (Req 4.4)."""
    c1 = Citation(document_id="d1", chunk_id="c1")
    c2 = Citation(document_id="d1", chunk_id="c2")
    c3 = Citation(document_id="d2", chunk_id="c3")
    findings = Research_Findings(
        findings=[
            Research_Finding(content="a", citations=[c1, c2]),
            Research_Finding(content="b", citations=[c3]),
        ]
    )

    assert findings.all_citations() == [c1, c2, c3]


def test_all_citations_empty_by_default():
    """A finding and findings collection default to empty citation lists."""
    assert Research_Finding(content="x").citations == []
    assert Research_Findings().all_citations() == []
    assert Draft(content="d").citations == []


def test_blackboard_counters_zero_initialized():
    """round_count and revision_count start at zero; bounds default correctly (Req 4.7)."""
    state = Blackboard_State(run_id="r", conversation_id="c", task="t")

    assert state.round_count == 0
    assert state.revision_count == 0
    assert state.max_rounds == DEFAULT_MAX_ROUNDS
    assert state.max_revisions == DEFAULT_MAX_REVISIONS
    assert state.plan is None
    assert state.research_findings is None
    assert state.draft is None
    assert state.critic_feedback is None
    assert state.termination_reason is None
    assert state.awaiting_approval is False


def test_termination_reason_values():
    """Termination_Reason carries exactly the five design values (Req 2.7)."""
    assert {r.value for r in Termination_Reason} == {
        "completed",
        "max-rounds-reached",
        "max-revisions-reached",
        "rejected",
        "aborted",
    }
