"""Unit tests for the reused RBAC / guardrail / rate-limit / tracing seams (Task 8.5).

These verify Phase 8 governance is enforced entirely by the **reused** Phase 5/6 seams —
no orchestrator, enterprise, or tool contract is modified:

* an agent run that could invoke an Integration_Tool is gated behind
  ``require_permission(Permission.RUN_AGENTS)`` — a Principal lacking it gets 403, and the
  write actions (slack.post_message / gmail.send_message / github.create_issue) are gated by
  the same run permission (Req 8.1, 8.2, 10.1, 10.2, 10.6, 13.6, 15.6);
* blocking an under-permissioned Principal records a credential-free security audit event
  (Req 8.2, 10.6);
* a guardrail block short-circuits before any Integration_Tool is invoked (Req 10.3);
* the per-principal rate limiter applies to integration-driving requests (Req 10.4);
* the ``act`` node produces ``validation_error`` (tool NOT invoked) and
  ``tool_execution_error`` observations and records one trace entry per invocation
  (Req 8.3, 8.4, 16.1);
* a failing trace export never changes the invocation outcome (Req 16.3).
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agentforge.agent.graph import (
    OBS_TOOL_EXECUTION_ERROR,
    OBS_TOOL_RESULT,
    OBS_VALIDATION_ERROR,
    Agent_Graph_Nodes,
)
from agentforge.agent.selection import Deterministic_Fallback_Strategy
from agentforge.agent.state import AgentState
from agentforge.api.deps import get_current_principal
from agentforge.api.errors import AppError
from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_enterprise_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.enterprise.base import Rate_Limiter
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Permission, Role
from agentforge.integrations.base import (
    Integration_Connector,
    Integration_Tool,
)
from agentforge.integrations.governance import audit_logger, record_integration_denial
from agentforge.integrations.slack import Mock_Slack_Connector, Slack_Tool
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.observability.guardrails.base import (
    Guardrail,
    Guardrail_Decision,
    Guardrail_Pipeline,
    Guardrail_Result,
    apply_input_guardrail,
)
from agentforge.observability.tracing_exporter import LangSmith_Tracing_Exporter
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tools.base import Tool_Call, Tool_Result, ToolError
from agentforge.tools.registry import Tool_Registry
from agentforge.tracing.base import Trace
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


def _wire_app(settings: Settings, *, enterprise=None):
    """Build an app whose registry includes a Slack tool via an injected mock connector."""
    from agentforge.main import create_app

    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    agent_ctx = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
        integration_connectors={"slack": Mock_Slack_Connector(messages=[{"text": "hi"}])},
    )
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    if enterprise is not None:
        app.state.enterprise_context = enterprise
    return app, agent_ctx


# --- RBAC: run_agents gating + write-action gate + denial audit --------------------


def test_run_agents_gating_blocks_viewer_and_allows_member():
    settings = _make_settings()
    app, _ctx = _wire_app(settings)
    # A VIEWER (no run_agents) is blocked from initiating a run that could invoke a tool.
    headers, _org, ent = install_enterprise_auth(app, settings, role=Role.VIEWER)
    client = TestClient(app, raise_server_exceptions=False)
    denied = client.post("/agent/run", json={"message": "hi"}, headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"
    assert denied.json()["error"]["details"]["required"] == "run_agents"

    # A MEMBER (has run_agents) can initiate the run.
    member_headers, _org2 = issue_principal_headers(
        ent, role=Role.MEMBER, org_name="Org2", email="member@example.com"
    )
    allowed = client.post("/agent/run", json={"message": "hi"}, headers=member_headers)
    assert allowed.status_code == 200


def test_slack_tool_registered_and_write_action_gated_by_same_run_permission():
    settings = _make_settings()
    app, agent_ctx = _wire_app(settings)
    # The Slack integration (a write-capable tool) is discoverable through the registry.
    names = {spec.name for spec in agent_ctx.tool_registry.list_specs()}
    assert "slack" in names
    # The write action is reachable only through /agent/run, which is gated by RUN_AGENTS,
    # so a VIEWER cannot drive slack.post_message.
    headers, _org, _ent = install_enterprise_auth(app, settings, role=Role.VIEWER)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/agent/run",
        json={"message": "post to #general"},
        headers=headers,
    )
    assert resp.status_code == 403


def test_denial_audit_event_records_principal_integration_action_without_secret():
    principal = Principal(
        kind=PrincipalKind.USER.value,
        user_id=uuid4(),
        key_id=None,
        org_id=uuid4(),
        role=Role.VIEWER,
        permissions=frozenset(),
    )
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    audit_logger.addHandler(handler)
    try:
        record_integration_denial(principal, "slack", "post_message")
    finally:
        audit_logger.removeHandler(handler)

    assert len(records) == 1
    logged = records[0]
    assert getattr(logged, "event") == "integration_action_denied"
    assert getattr(logged, "integration") == "slack"
    assert getattr(logged, "action") == "post_message"
    assert str(principal.org_id) == getattr(logged, "org_id")


# --- Guardrail short-circuit -------------------------------------------------------


class _BlockingGuardrail(Guardrail):
    @property
    def name(self) -> str:
        return "always_block"

    def check(self, content: str) -> Guardrail_Result:
        return Guardrail_Result(Guardrail_Decision.BLOCK, reason="blocked")


def test_guardrail_block_short_circuits_before_any_integration_tool_invocation():
    connector = Mock_Slack_Connector()
    tool = Slack_Tool(connector, timeout_seconds=5, max_results=20)
    pipeline = Guardrail_Pipeline([_BlockingGuardrail()])

    def _downstream():
        # Would invoke the integration tool; must never run on a blocked input.
        return tool.invoke({"action": "post_message", "channel": "#c", "text": "x"})

    with pytest.raises(AppError) as excinfo:
        apply_input_guardrail(pipeline, "bad input", _downstream)
    assert excinfo.value.code == "guardrail_blocked"
    # The Integration_Tool's connector was never called (Req 10.3).
    assert connector.calls == []


# --- Rate limiting -----------------------------------------------------------------


class _AlwaysRateLimited(Rate_Limiter):
    def check(self, principal_key: str) -> None:
        raise AppError("rate_limited", "Too many requests.", 429)


def test_rate_limit_applies_to_integration_driving_requests():
    settings = _make_settings()
    enterprise = build_enterprise_context(settings, rate_limiter=_AlwaysRateLimited())
    app, _ctx = _wire_app(settings, enterprise=enterprise)
    headers, _org = issue_principal_headers(enterprise, role=Role.MEMBER)
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/agent/run", json={"message": "hi"}, headers=headers)
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "rate_limited"


# --- act-node observations + trace entry per invocation ----------------------------


def _nodes_with_slack(connector: Integration_Connector, trace=None) -> Agent_Graph_Nodes:
    registry = Tool_Registry()
    registry.register(Slack_Tool(connector, timeout_seconds=5, max_results=20))
    return Agent_Graph_Nodes(registry, Deterministic_Fallback_Strategy(), trace)


def _state_with_call(tool_name: str, arguments: dict) -> AgentState:
    return AgentState(
        run_id="run-1",
        conversation_id="conv-1",
        user_request="do it",
        pending_tool_call=Tool_Call(tool_name=tool_name, arguments=arguments),
    )


def test_act_node_validation_error_does_not_invoke_tool():
    connector = Mock_Slack_Connector()
    nodes = _nodes_with_slack(connector)
    # Missing the required "channel" argument -> validation_error, tool NOT invoked.
    state = _state_with_call("slack", {"action": "read_channel"})
    result = nodes.act(state)
    observation = result["pending_observation"]
    assert observation.kind == OBS_VALIDATION_ERROR
    assert connector.calls == []


def test_act_node_contains_tool_execution_error_as_observation():
    class _RaisingTool(Integration_Tool):
        @property
        def name(self) -> str:
            return "raiser"

        @property
        def description(self) -> str:
            return "raises a ToolError"

        @property
        def input_schema(self) -> dict:
            return {"type": "object", "properties": {}, "additionalProperties": True}

        def _dispatch(self, arguments, connector):
            raise ToolError("boom")

    registry = Tool_Registry()
    registry.register(_RaisingTool(Mock_Slack_Connector(), timeout_seconds=5, max_results=20))
    nodes = Agent_Graph_Nodes(registry, Deterministic_Fallback_Strategy(), None)
    state = _state_with_call("raiser", {})
    observation = nodes.act(state)["pending_observation"]
    assert observation.kind == OBS_TOOL_EXECUTION_ERROR


def test_act_node_records_one_trace_entry_per_invocation():
    trace = InMemory_Trace_Recorder()
    connector = Mock_Slack_Connector(messages=[{"text": "hi"}])
    nodes = _nodes_with_slack(connector, trace)
    state = _state_with_call("slack", {"action": "read_channel", "channel": "#c"})
    observation = nodes.act(state)["pending_observation"]
    assert observation.kind == OBS_TOOL_RESULT
    # Exactly one tool_call trace entry recorded for this invocation, naming the tool.
    entries = trace.get_trace(nodes_org(), "run-1").entries
    tool_calls = [e for e in entries if e.step_type == "tool_call"]
    assert len(tool_calls) == 1
    assert tool_calls[0].tool_name == "slack"
    assert tool_calls[0].outcome == OBS_TOOL_RESULT


def nodes_org():
    # The act node scopes the trace to the ambient tenant (current_org()); with no org set
    # in this unit context it records under the default (None) tenant.
    from agentforge.enterprise.tenancy import current_org

    return current_org()


# --- export-failure suppression ----------------------------------------------------


class _RaisingClient:
    def create_run(self, **kwargs):
        raise RuntimeError("export boom")


def test_trace_export_failure_never_changes_invocation_outcome():
    # A successful Integration_Tool invocation.
    connector = Mock_Slack_Connector(messages=[{"text": "hi"}])
    tool = Slack_Tool(connector, timeout_seconds=5, max_results=20)
    result = tool.invoke({"action": "read_channel", "channel": "#c"})
    assert result.ok is True

    # Exporting the run's trace fails internally, but the failure is suppressed and the
    # already-produced invocation result is unchanged (Req 16.3).
    exporter = LangSmith_Tracing_Exporter("k", client=_RaisingClient())
    assert exporter.export(Trace(run_id="run-1"), org_id=uuid4(), user_id=None) is None
    assert result.ok is True
    assert isinstance(result, Tool_Result)
