"""Property-based test for total connector-failure mapping (Property 4)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.integrations.base import (
    ConnectorError,
    Rate_Limited_Error,
    Unauthorized_Error,
    Upstream_Error,
)
from tests.integrations_helpers import Probe_Tool, Spy_Connector

# Each connector failure class maps onto exactly one fixed error code.
_FAILURE_KINDS = {
    "unauthorized": (Unauthorized_Error, "integration_unauthorized"),
    "rate_limited": (Rate_Limited_Error, "integration_rate_limited"),
    "upstream": (Upstream_Error, "integration_upstream_error"),
    "base_connector": (ConnectorError, "integration_upstream_error"),
}


# Feature: agentforge-integrations, Property 4: Connector failure mapping is total over the
# failure vocabulary.
@hyp_settings(max_examples=120, deadline=None)
@given(
    kind=st.sampled_from(sorted(_FAILURE_KINDS)),
    action=st.sampled_from(["read", "write"]),
)
def test_connector_failure_maps_to_fixed_code(kind, action):
    """Feature: agentforge-integrations, Property 4: For any integration action and any
    connector failure class (Unauthorized_Error -> integration_unauthorized,
    Rate_Limited_Error -> integration_rate_limited, Upstream_Error / other ConnectorError ->
    integration_upstream_error), invoke returns a Tool_Result with ok == false carrying
    exactly the corresponding fixed error code and never raises.

    Validates: Requirements 7.2, 7.3, 7.4, 12.6
    """
    exc_cls, expected_code = _FAILURE_KINDS[kind]
    connector = Spy_Connector(available=True, raises=exc_cls("provider said no"))
    tool = Probe_Tool(connector, timeout_seconds=5.0, max_results=10)

    # Must not raise for any anticipated failure class.
    result = tool.invoke({"action": action})

    assert result.ok is False
    assert result.data["error_code"] == expected_code
