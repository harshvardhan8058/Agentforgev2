"""Property-based test for the Integration_Tool Disabled short-circuit (Property 3)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from tests.integrations_helpers import Probe_Tool, Spy_Connector

_arguments = st.dictionaries(
    keys=st.text(max_size=8),
    values=st.one_of(st.integers(), st.text(max_size=8), st.booleans()),
    max_size=5,
)


# Feature: agentforge-integrations, Property 3: A Disabled tool invoked directly returns
# integration_disabled with no connector call.
@hyp_settings(max_examples=150, deadline=None)
@given(arguments=_arguments)
def test_disabled_tool_returns_disabled_without_connector_call(arguments):
    """Feature: agentforge-integrations, Property 3: For any Integration_Tool whose
    connector is unavailable and any argument dictionary, invoke returns a Tool_Result with
    ok == false carrying integration_disabled, and the connector's operations are never
    called (zero network path).

    Validates: Requirements 7.1, 3.2, 5.5, 10.5
    """
    connector = Spy_Connector(available=False)
    tool = Probe_Tool(connector, timeout_seconds=5.0, max_results=10)

    result = tool.invoke(arguments)

    # The tool mirrors the connector's disabled state (Req 5.5).
    assert tool.available is False
    # A contained failure carrying the fixed disabled code is returned (Req 7.1).
    assert result.ok is False
    assert result.data["error_code"] == "integration_disabled"
    # No connector operation was ever invoked (Req 3.2, 10.5).
    assert connector.calls == []
