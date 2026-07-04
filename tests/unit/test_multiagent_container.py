"""Unit tests for the Phase 4 composition root wiring (Task 11.1).

These verify that :func:`build_multi_agent_context` wires the multi-agent object graph
correctly:

* The four built-in roles all reference the **same** existing single-agent
  ``Agent_Orchestrator`` from the reused :class:`AgentContext` — no new reasoning loop
  is created for the multi-agent layer (Req 11.1).
* The keyless default policy is :class:`Auto_Approve_Policy` when the settings do not
  configure ``approval_policy`` (Req 5.7).
* Every collaborator is injectable via ``**overrides`` so tests can pass keyless
  in-memory doubles and an alternate policy without touching the settings (Req 12.1).
"""

from __future__ import annotations

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_multi_agent_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.multiagent.approval import (
    Auto_Approve_Policy,
    Human_In_The_Loop_Policy,
)
from agentforge.multiagent.roles.critic import Critic_Agent
from agentforge.multiagent.roles.planner import Planner_Agent
from agentforge.multiagent.roles.researcher import Researcher_Agent
from agentforge.multiagent.roles.writer import Writer_Agent
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


def _make_settings(**overrides) -> Settings:
    base = dict(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )
    base.update(overrides)
    return Settings(**base)


def _build_keyless_agent_context(settings: Settings):
    """Build a keyless :class:`AgentContext` with all in-memory doubles injected."""
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    return build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )


def test_roles_share_single_agent_orchestrator():
    """All four registered roles reference the SAME Agent_Orchestrator from AgentContext (Req 11.1)."""
    settings = _make_settings()
    agent_ctx = _build_keyless_agent_context(settings)

    ctx = build_multi_agent_context(settings, agent=agent_ctx)

    shared: Agent_Orchestrator = agent_ctx.orchestrator
    for role_id in ("planner", "researcher", "writer", "critic"):
        role = ctx.role_registry.resolve(role_id)
        assert role is not None, f"role {role_id!r} was not registered"
        # Every role holds the very same underlying single-agent orchestrator instance
        # (identity, not equality) — no new reasoning loop was introduced (Req 11.1).
        assert role._orchestrator is shared

    # Sanity: the four roles are exactly the built-in ones.
    resolved_types = {
        type(ctx.role_registry.resolve("planner")),
        type(ctx.role_registry.resolve("researcher")),
        type(ctx.role_registry.resolve("writer")),
        type(ctx.role_registry.resolve("critic")),
    }
    assert resolved_types == {Planner_Agent, Researcher_Agent, Writer_Agent, Critic_Agent}


def test_default_policy_is_auto_approve():
    """With no configured ``approval_policy`` the gate uses ``Auto_Approve_Policy`` (Req 5.7)."""
    settings = _make_settings()  # keyless default => "auto"
    agent_ctx = _build_keyless_agent_context(settings)

    ctx = build_multi_agent_context(settings, agent=agent_ctx)

    assert isinstance(ctx.approval_policy, Auto_Approve_Policy)
    # The gate itself uses that policy (checked via a non-private property probe).
    assert isinstance(ctx.gate._policy, Auto_Approve_Policy)


def test_overrides_inject_in_memory_store_and_policy():
    """``**overrides`` propagate injected run_store / approval_policy end-to-end (Req 12.1)."""
    settings = _make_settings()
    agent_ctx = _build_keyless_agent_context(settings)

    injected_store = InMemory_Multi_Agent_Run_Store()
    injected_policy = Human_In_The_Loop_Policy()

    ctx = build_multi_agent_context(
        settings,
        agent=agent_ctx,
        run_store=injected_store,
        approval_policy=injected_policy,
    )

    # The injected collaborators are used verbatim, not rebuilt.
    assert ctx.run_store is injected_store
    assert ctx.approval_policy is injected_policy
    assert ctx.gate._policy is injected_policy
