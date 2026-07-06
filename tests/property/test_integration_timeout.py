"""Property-based test for the Timeout_Budget guarantee (Property 5)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from tests.integrations_helpers import Probe_Tool, Spy_Connector


# Feature: agentforge-integrations, Property 5: Exceeding the Timeout_Budget always yields
# integration_timeout.
@hyp_settings(max_examples=100, deadline=None)
@given(
    latency=st.floats(min_value=0.05, max_value=0.15),
    action=st.sampled_from(["read", "write"]),
)
def test_exceeding_timeout_budget_yields_timeout(latency, action):
    """Feature: agentforge-integrations, Property 5: For any integration action and any
    connector whose operation takes longer than the configured Timeout_Budget, invoke aborts
    the invocation and returns a Tool_Result with ok == false carrying integration_timeout.

    Validates: Requirements 6.1, 6.2
    """
    # A connector op slower than the (tiny) configured timeout.
    connector = Spy_Connector(available=True, items=[1, 2, 3], latency=latency)
    tool = Probe_Tool(connector, timeout_seconds=0.01, max_results=10)

    result = tool.invoke({"action": action})

    assert result.ok is False
    assert result.data["error_code"] == "integration_timeout"
