"""Unit tests for the guardrails router + entry-point wrapping (Task 14.3).

Drive the real FastAPI app through ``TestClient`` with only keyless in-memory contexts
wired on ``app.state`` (an ``EnterpriseContext`` for auth + an ``ObservabilityContext``
holding a custom ``Guardrail_Pipeline``, plus the RAG / agent / multi-agent contexts for
the wrapped entry points). No Postgres, Redis, or external credential is required.

Covered (Req 5.2, 5.3, 5.4, 5.5, 5.6):

* ``GET /guardrails/config`` — ordered active guardrail names + kinds;
* ``POST /guardrails/evaluate`` — allow / flag / block responses;
* a blocked input at each of the three entry points (``/query``, ``/agent/run``,
  ``/multi-agent/runs``) -> 400 ``guardrail_blocked`` with the downstream never invoked;
* a flagged input proceeding, with the flags surfaced on the response.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_multi_agent_context,
    build_observability_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.multiagent.approval import Auto_Approve_Policy
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.observability.guardrails.base import (
    Guardrail,
    Guardrail_Decision,
    Guardrail_Pipeline,
    Guardrail_Result,
)
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8

# Sentinel tokens the custom guardrails react to.
_BLOCK_TOKEN = "BLOCKME"
_FLAG_TOKEN = "FLAGME"


class _Block_Guardrail(Guardrail):
    """Blocks content containing the block sentinel."""

    @property
    def name(self) -> str:
        return "test_block"

    def check(self, content: str) -> Guardrail_Result:
        if _BLOCK_TOKEN in content:
            return Guardrail_Result(
                Guardrail_Decision.BLOCK, reason="contains blocked token"
            )
        return Guardrail_Result(Guardrail_Decision.ALLOW)


class _Flag_Guardrail(Guardrail):
    """Flags (but does not block) content containing the flag sentinel."""

    @property
    def name(self) -> str:
        return "test_flag"

    def check(self, content: str) -> Guardrail_Result:
        if _FLAG_TOKEN in content:
            return Guardrail_Result(
                Guardrail_Decision.FLAG, flags=("flagged-content",)
            )
        return Guardrail_Result(Guardrail_Decision.ALLOW)


class _Echo_Provider(Fallback_Provider):
    """A keyless provider whose completion echoes the flag sentinel back.

    Ensures the produced output carries the flag sentinel so the OUTPUT guardrail
    pipeline annotates the response — demonstrating a flagged input proceeding with its
    flags attached (Req 5.5, 5.6).
    """

    def generate(self, prompt: str):  # type: ignore[override]
        result = super().generate(prompt)
        if _FLAG_TOKEN in prompt:
            # Return a result whose text contains the sentinel so the output pipeline flags it.
            return type(result)(
                text=f"{result.text} {_FLAG_TOKEN}",
                provider=result.provider,
            )
        return result


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


def _pipeline() -> Guardrail_Pipeline:
    # Flag first, then block — block still short-circuits when present (Req 5.1, 5.3).
    return Guardrail_Pipeline([_Flag_Guardrail(), _Block_Guardrail()])


class _Spy_Orchestrator:
    """Records whether ``run`` was invoked (to assert downstream prevention)."""

    def __init__(self) -> None:
        self.called = False

    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.called = True
        raise AssertionError("downstream orchestrator must not be invoked on a block")


@pytest.fixture
def wired():
    """Return ``(app, client, headers, spies)`` fully wired with a custom guardrail pipeline."""
    settings = _make_settings()
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=_Echo_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    agent_ctx = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    multi_ctx = build_multi_agent_context(
        settings,
        agent=agent_ctx,
        run_store=InMemory_Multi_Agent_Run_Store(),
        approval_policy=Auto_Approve_Policy(),
    )
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = multi_ctx
    app.state.observability_context = build_observability_context(
        settings, app=app_ctx, guardrail_pipeline=_pipeline()
    )
    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    client = TestClient(app, headers=headers, raise_server_exceptions=False)
    return app, client, multi_ctx


# --- GET /guardrails/config -------------------------------------------------------


def test_config_lists_ordered_names_and_kinds(wired):
    _app, client, _multi = wired
    resp = client.get("/guardrails/config")
    assert resp.status_code == 200
    guardrails = resp.json()["guardrails"]
    # Order mirrors the pipeline's stable configured order (flag then block).
    assert [g["name"] for g in guardrails] == ["test_flag", "test_block"]
    assert [g["kind"] for g in guardrails] == ["_Flag_Guardrail", "_Block_Guardrail"]


# --- POST /guardrails/evaluate ----------------------------------------------------


def test_evaluate_allow(wired):
    _app, client, _multi = wired
    resp = client.post("/guardrails/evaluate", json={"content": "totally fine"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "allow"
    assert body["flags"] == []
    assert body["reason"] is None


def test_evaluate_flag(wired):
    _app, client, _multi = wired
    resp = client.post("/guardrails/evaluate", json={"content": f"please {_FLAG_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "flag"
    assert body["flags"] == ["flagged-content"]


def test_evaluate_block(wired):
    _app, client, _multi = wired
    resp = client.post("/guardrails/evaluate", json={"content": f"do {_BLOCK_TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["decision"] == "block"
    assert body["reason"] == "contains blocked token"


# --- blocked input at each entry point (downstream not invoked) -------------------


def test_query_blocked_input_does_not_invoke_downstream(wired):
    app, client, _multi = wired
    from agentforge.api.deps import get_rag_service

    called = {"hit": False}

    class _SpyRag:
        def answer(self, *args, **kwargs):
            called["hit"] = True
            raise AssertionError("RAG_Service must not be invoked on a block")

    app.dependency_overrides[get_rag_service] = lambda: _SpyRag()
    try:
        resp = client.post("/query", json={"query": f"please {_BLOCK_TOKEN} now"})
    finally:
        app.dependency_overrides.pop(get_rag_service, None)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "guardrail_blocked"
    assert called["hit"] is False


def test_agent_blocked_input_does_not_invoke_downstream(wired):
    app, client, _multi = wired
    from agentforge.api.deps import get_orchestrator

    spy = _Spy_Orchestrator()
    app.dependency_overrides[get_orchestrator] = lambda: spy
    try:
        resp = client.post("/agent/run", json={"message": f"{_BLOCK_TOKEN} please"})
    finally:
        app.dependency_overrides.pop(get_orchestrator, None)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "guardrail_blocked"
    assert spy.called is False


def test_multi_agent_blocked_input_creates_no_run(wired):
    _app, client, multi_ctx = wired
    resp = client.post("/multi-agent/runs", json={"task": f"{_BLOCK_TOKEN} the task"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "guardrail_blocked"
    # The block short-circuits before the run is created, so no run is ever persisted —
    # evidence the multi-agent orchestrator was never reached (Req 5.4).
    assert multi_ctx.run_store._runs == {}


# --- flagged input proceeds with annotations --------------------------------------


def test_query_flagged_input_proceeds_with_flags(wired):
    _app, client, _multi = wired
    # Ingest a doc so the query is grounded, then send a flagged (non-blocking) input.
    body = b"AgentForge grounds answers in retrieved chunks and cites their sources."
    assert (
        client.post(
            "/documents", files={"file": ("doc.txt", body, "text/plain")}
        ).status_code
        == 201
    )
    resp = client.post("/query", json={"query": f"How does {_FLAG_TOKEN} answer?"})
    assert resp.status_code == 200
    body = resp.json()
    # The flagged input proceeded (200) and the output pipeline attached the annotation.
    assert "flagged-content" in body["flags"]
