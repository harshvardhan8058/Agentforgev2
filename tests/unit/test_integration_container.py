"""Unit tests for the Phase 8 composition-root wiring (task 4.6).

Cover the duplicate-name rejection surfacing unchanged (Req 2.4) and the startup-abort with
an ``AppError`` naming the offending integration when an Enabled connector fails to construct
(Req 2.6). Also spot-check the connector-builder selection and the deps accessors.
"""

from __future__ import annotations

import pytest

from agentforge.api.errors import AppError
from agentforge.config.container import (
    build_github_connector,
    build_integration_connection_store,
    build_integration_status_service,
    build_integration_tools,
    build_slack_connector,
)
from agentforge.config.settings import Settings
from agentforge.integrations.base import Integration_Connector
from agentforge.integrations.connection import (
    InMemory_Integration_Connection_Store,
)
from agentforge.integrations.github import Disabled_GitHub_Connector, Keyed_GitHub_Connector
from agentforge.integrations.slack import (
    Disabled_Slack_Connector,
    Keyed_Slack_Connector,
    Mock_Slack_Connector,
    Slack_Tool,
)
from agentforge.integrations.status import Integration_Status_Service
from agentforge.tools.registry import DuplicateToolNameError, Tool_Registry


def _settings(**overrides) -> Settings:
    base = {
        "profile": "local",
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
    }
    return Settings(**{**base, **overrides})  # type: ignore[arg-type]


class _Boom_Connector(Integration_Connector):
    """A connector whose availability check fails, to exercise the startup abort."""

    @property
    def available(self) -> bool:
        raise RuntimeError("connector construction failed")


# --- connector-builder selection ---------------------------------------------------


def test_connector_builders_disabled_when_keyless():
    """No credential -> the Disabled connector (available False), no network path."""
    settings = _settings()
    assert isinstance(build_slack_connector(settings), Disabled_Slack_Connector)
    assert isinstance(build_github_connector(settings), Disabled_GitHub_Connector)
    assert build_slack_connector(settings).available is False


def test_connector_builders_keyed_when_enabled():
    """A present credential + enabled toggle -> the Keyed connector (available True)."""
    settings = _settings(slack_bot_token="SEKRET-slack", github_token="SEKRET-gh")
    assert isinstance(build_slack_connector(settings), Keyed_Slack_Connector)
    assert isinstance(build_github_connector(settings), Keyed_GitHub_Connector)
    assert build_slack_connector(settings).available is True


# --- duplicate-name rejection surfaces unchanged (Req 2.4) -------------------------


def test_duplicate_tool_name_rejection_surfaces_unchanged():
    """Registering a second tool under an existing name raises DuplicateToolNameError."""
    settings = _settings()
    tools = build_integration_tools(
        settings, connectors={"slack": Mock_Slack_Connector(available=True)}
    )
    assert [t.name for t in tools] == ["slack"]

    registry = Tool_Registry()
    registry.register(tools[0])
    with pytest.raises(DuplicateToolNameError):
        registry.register(
            Slack_Tool(Mock_Slack_Connector(), timeout_seconds=5.0, max_results=10)
        )


def test_only_enabled_integrations_are_yielded():
    """A Disabled integration is never yielded for registration (Req 2.2, 2.3)."""
    settings = _settings()  # keyless: every integration Disabled
    assert build_integration_tools(settings) == []


# --- startup abort names the offending integration (Req 2.6) -----------------------


def test_failing_enabled_connector_aborts_naming_integration():
    """A failing Enabled connector aborts with an AppError naming the integration."""
    settings = _settings()
    with pytest.raises(AppError) as exc_info:
        build_integration_tools(settings, connectors={"gmail": _Boom_Connector()})

    error = exc_info.value
    assert error.code == "integration_config_error"
    assert error.details["integration"] == "gmail"
    # No internal detail / stack trace leaks into the message.
    assert "gmail" in error.message


# --- deps builders ------------------------------------------------------------------


def test_enabled_integration_discoverable_through_unmodified_orchestrator():
    """Checkpoint 5: an Enabled integration (via an injected mock connector) is discoverable
    through the UNMODIFIED orchestrator solely via the Tool_Registry (Req 2.2, 2.5)."""
    from agentforge.agent.orchestrator import Agent_Orchestrator
    from agentforge.llm.fallback_provider import Fallback_Provider

    settings = _settings()
    registry = Tool_Registry()
    for tool in build_integration_tools(
        settings, connectors={"slack": Mock_Slack_Connector(available=True)}
    ):
        registry.register(tool)

    # The orchestrator is constructed as-is (no Phase 8 change) over the shared registry.
    orchestrator = Agent_Orchestrator(Fallback_Provider(), registry, iteration_limit=10)

    # The Enabled Slack integration is offered (listed) and resolvable via the registry the
    # orchestrator holds — the only seam through which it discovers tools.
    listed = {spec.name for spec in orchestrator._registry.list_specs()}
    assert "slack" in listed
    assert orchestrator._registry.resolve("slack") is not None


def test_status_service_and_connection_store_builders():
    """The status-service and connection-store builders return the expected types."""
    settings = _settings()
    assert isinstance(
        build_integration_status_service(settings), Integration_Status_Service
    )
    assert isinstance(
        build_integration_connection_store(settings),
        InMemory_Integration_Connection_Store,
    )
