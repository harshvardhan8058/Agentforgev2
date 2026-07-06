"""Unit tests for the Integration_Tool base helpers (task 1.7).

Cover the success-result shape, the error-result shape, and the availability mirror both
true and false (Req 1.4, 5.5).
"""

from __future__ import annotations

from agentforge.integrations.base import IntegrationErrorCode
from tests.integrations_helpers import PROBE_TOOL_NAME, Probe_Tool, Spy_Connector


def test_success_result_shape():
    """A successful invocation returns ok=True with populated content and data (Req 1.4)."""
    connector = Spy_Connector(available=True, items=["a", "b"])
    tool = Probe_Tool(connector, timeout_seconds=5.0, max_results=10)

    result = tool.invoke({"action": "read"})

    assert result.ok is True
    assert result.tool_name == PROBE_TOOL_NAME
    assert result.content  # non-empty human-readable summary
    assert result.data["items"] == ["a", "b"]
    # A success result carries no error_code.
    assert "error_code" not in result.data


def test_write_success_result_uses_supplied_content():
    """A write dispatch surfaces its own content summary and outcome data."""
    connector = Spy_Connector(available=True)
    tool = Probe_Tool(connector, timeout_seconds=5.0, max_results=10)

    result = tool.invoke({"action": "write", "text": "hello"})

    assert result.ok is True
    assert result.content == "wrote"
    assert result.data["written"] is True
    assert result.data["text"] == "hello"
    assert connector.calls == [("write", {"text": "hello"})]


def test_error_result_shape_when_disabled():
    """A Disabled invocation returns ok=False carrying the fixed error code (Req 7.1)."""
    connector = Spy_Connector(available=False)
    tool = Probe_Tool(connector, timeout_seconds=5.0, max_results=10)

    result = tool.invoke({"action": "read"})

    assert result.ok is False
    assert result.data["error_code"] == IntegrationErrorCode.DISABLED.value
    assert isinstance(result.content, str) and result.content


def test_available_mirrors_connector_true_and_false():
    """The tool's ``available`` tracks its connector's flag both ways (Req 5.5)."""
    available_tool = Probe_Tool(
        Spy_Connector(available=True), timeout_seconds=5.0, max_results=10
    )
    disabled_tool = Probe_Tool(
        Spy_Connector(available=False), timeout_seconds=5.0, max_results=10
    )

    assert available_tool.available is True
    assert disabled_tool.available is False
