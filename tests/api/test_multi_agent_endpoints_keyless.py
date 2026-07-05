"""Keyless API integration tests for the Phase 4 multi-agent endpoints (Task 12.3).

These drive the real FastAPI app through ``TestClient`` end to end using only keyless
in-memory doubles injected through the composition root (Fallback LLM + deterministic
fake embedder + Chroma + in-memory conversation store + in-memory trace + in-memory
multi-agent run store + Auto_Approve_Policy). No Postgres, Redis, or external credential
is required, so the whole module runs in the fast suite (``pytest -m 'not integration'``).

Covers Req 9.1-9.6, 5.5, 6.1, 7.6, 12.1.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_multi_agent_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.multiagent.approval import Auto_Approve_Policy
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


@pytest.fixture
def client() -> TestClient:
    """A TestClient wired with keyless in-memory doubles + Auto_Approve_Policy."""
    settings = _make_settings()
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
    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    return TestClient(app, headers=headers, raise_server_exceptions=False)


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse SSE frames into a list of ``(event_type, data)`` tuples."""
    events: list[tuple[str, dict]] = []
    event_type = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event_type = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
            events.append((event_type, payload))
    return events


# --- POST /multi-agent/runs -------------------------------------------------------


def test_start_run_returns_201_and_id(client: TestClient):
    """POST returns 201 with a run id and conversation id under auto-approve (Req 9.1)."""
    resp = client.post(
        "/multi-agent/runs",
        json={"task": "Explain caching strategies"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["run_id"]
    assert body["conversation_id"]
    # Under Auto_Approve_Policy the run runs to completion synchronously.
    assert body["status"] == "terminated"


# --- GET /multi-agent/runs/{id} ---------------------------------------------------


def test_run_result_endpoint_returns_final_output_and_trace_when_terminated(
    client: TestClient,
):
    """GET returns the terminal reason, final output, and the ordered role trace (Req 9.4, 6.1)."""
    start = client.post(
        "/multi-agent/runs", json={"task": "Explain caching strategies"}
    ).json()
    run_id = start["run_id"]

    resp = client.get(f"/multi-agent/runs/{run_id}")
    assert resp.status_code == 200
    body = resp.json()

    assert body["run_id"] == run_id
    assert body["status"] == "terminated"
    assert body["termination_reason"] == "completed"

    # Final_Output is present with the approved Draft content (Req 8.3, 2.3).
    assert body["final_output"] is not None
    assert body["final_output"]["content"]
    # Trace carries a role: entry per built-in role, attributed with role_id (Req 6.1).
    role_entries = [
        entry for entry in body["trace"] if entry["step_type"].startswith("role:")
    ]
    role_ids_in_order = [
        entry["step_type"].removeprefix("role:") for entry in role_entries
    ]
    assert role_ids_in_order[:4] == ["planner", "researcher", "writer", "critic"]
    for entry in role_entries[:4]:
        assert entry["role_id"] == entry["step_type"].removeprefix("role:")
    # Ordinals are contiguous ascending.
    ordinals = [entry["ordinal"] for entry in body["trace"]]
    assert ordinals == sorted(ordinals)


# --- POST /multi-agent/runs/{id}/stream -------------------------------------------


def test_stream_endpoint_yields_sse_frames_and_terminates(client: TestClient):
    """Stream emits an early AGENT_STARTED and terminates with exactly one COMPLETION (Req 7.6)."""
    start = client.post(
        "/multi-agent/runs", json={"task": "Explain caching strategies"}
    ).json()
    run_id = start["run_id"]

    resp = client.post(f"/multi-agent/runs/{run_id}/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    assert events, "expected at least one SSE event"

    types = [t for t, _ in events]
    # First event is agent_started for the Planner (Req 7.1).
    assert types[0] == "agent_started"
    assert events[0][1]["role_id"] == "planner"

    # Exactly one terminal event, and it is the last frame (Req 7.6, 7.8).
    terminals = [t for t in types if t in {"completion", "error"}]
    assert terminals == ["completion"]
    assert types[-1] == "completion"

    # Sequences are strictly ascending 0..N-1 (Req 7.4).
    sequences = [data["sequence"] for _, data in events]
    assert sequences == list(range(len(events)))


# --- POST /multi-agent/runs/{id}/approval -----------------------------------------


def test_approval_endpoint_rejects_when_run_not_paused(client: TestClient):
    """Approval to an already-terminated run -> run-not-awaiting-approval envelope (Req 5.5)."""
    start = client.post(
        "/multi-agent/runs", json={"task": "Explain caching strategies"}
    ).json()
    run_id = start["run_id"]

    # The auto-approve run has already terminated — no checkpoint is persisted.
    resp = client.post(
        f"/multi-agent/runs/{run_id}/approval",
        json={"type": "approve"},
    )
    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]["code"] == "run-not-awaiting-approval"

    # The run's persisted state is unchanged (still terminated with the same reason).
    check = client.get(f"/multi-agent/runs/{run_id}").json()
    assert check["status"] == "terminated"
    assert check["termination_reason"] == "completed"


# --- 404 for unknown run id -------------------------------------------------------


def test_unknown_run_id_returns_404(client: TestClient):
    """GET and POST /approval against an unknown run id return 404 via the envelope (Req 9.6)."""
    resp = client.get("/multi-agent/runs/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"

    resp = client.post(
        "/multi-agent/runs/does-not-exist/approval",
        json={"type": "approve"},
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
