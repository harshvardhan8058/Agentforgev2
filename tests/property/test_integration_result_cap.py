"""Property-based test for the single-invocation result cap (Property 6)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from tests.integrations_helpers import Probe_Tool, Spy_Connector


# Feature: agentforge-integrations, Property 6: A single invocation never returns more than
# the configured result cap.
@hyp_settings(max_examples=150, deadline=None)
@given(n=st.integers(min_value=0, max_value=60), c=st.integers(min_value=0, max_value=60))
def test_result_cap_is_min_of_n_and_c(n, c):
    """Feature: agentforge-integrations, Property 6: For any configured maximum result count
    C and any connector returning N items, the Tool_Result produced by a read/search/list
    action contains min(N, C) items, so the returned volume never exceeds C.

    Validates: Requirements 6.3, 12.4, 13.3, 14.3, 15.3
    """
    items = list(range(n))
    connector = Spy_Connector(available=True, items=items)
    tool = Probe_Tool(connector, timeout_seconds=5.0, max_results=c)

    result = tool.invoke({"action": "read"})

    assert result.ok is True
    assert len(result.data["items"]) == min(n, c)
    # The returned volume never exceeds the configured cap.
    assert len(result.data["items"]) <= c
