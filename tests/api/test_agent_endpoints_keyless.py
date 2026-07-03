"""Keyless API integration tests for the Phase 3 agent + conversation endpoints.

These drive the real FastAPI app through ``TestClient`` end to end using only keyless,
in-memory doubles injected through the composition root (Fallback LLM + deterministic
fake embedder + Chroma + in-memory conversation store + in-memory trace + disabled web
search). No Postgres, Redis, or external credential is required, so the whole module runs
in the fast suite (``pytest -m 'not integration'``).

Covers:
* ``/agent/run`` end-to-end grounded answer with a single termination reason (Task 16.4).
* ``/agent/stream`` SSE stream ending in exactly one terminal event, with the first event
  arriving promptly and incrementally (Tasks 16.4, 13.3 — Req 9.1, 9.2, 9.6, 9.9).
* Conversation create / append / history round-trip (Req 8.1-8.4).
* Unknown conversation and run ids return ``404`` through the error envelope (Task 16.5).
"""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import build_agent_context, build_app_context
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

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
    """A TestClient wired with keyless in-memory doubles (no lifespan/infra)."""
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
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    return TestClient(app, raise_server_exceptions=False)


def _ingest(client: TestClient) -> None:
    body = b"AgentForge grounds answers in retrieved chunks and cites their sources."
    resp = client.post(
        "/documents", files={"file": ("doc.txt", body, "text/plain")}
    )
    assert resp.status_code == 201


# --- conversations ----------------------------------------------------------------


def test_conversation_create_append_history_roundtrip(client: TestClient):
    conversation_id = client.post("/conversations").json()["conversation_id"]

    resp = client.post(
        f"/conversations/{conversation_id}/messages",
        json={"role": "user", "content": "hello"},
    )
    assert resp.status_code == 201
    assert resp.json() == {"role": "user", "content": "hello", "position": 0}

    history = client.get(f"/conversations/{conversation_id}").json()
    assert history["conversation_id"] == conversation_id
    assert [(m["role"], m["content"], m["position"]) for m in history["messages"]] == [
        ("user", "hello", 0)
    ]


def test_append_auto_creates_unknown_conversation(client: TestClient):
    resp = client.post(
        "/conversations/brand-new/messages",
        json={"role": "user", "content": "hi"},
    )
    assert resp.status_code == 201
    assert client.get("/conversations/brand-new").status_code == 200


def test_get_unknown_conversation_returns_404_envelope(client: TestClient):
    resp = client.get("/conversations/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


# --- /agent/run -------------------------------------------------------------------


def test_agent_run_returns_grounded_answer_with_single_termination_reason(
    client: TestClient,
):
    _ingest(client)
    resp = client.post("/agent/run", json={"message": "How does AgentForge answer?"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["run_id"]
    assert body["conversation_id"]
    assert body["answer"]
    # Exactly one termination reason from the allowed set (Req 1.7).
    assert body["termination_reason"] in {"final-answer", "iteration-limit-reached"}
    # Grounded via the RAG_Tool -> at least one citation surfaced.
    assert len(body["citations"]) >= 1

    # The final assistant message was persisted to the conversation (Req 8.5).
    history = client.get(f"/conversations/{body['conversation_id']}").json()
    roles = [m["role"] for m in history["messages"]]
    assert roles == ["user", "assistant"]

    # The run trace is retrievable and ordered (Req 10.3).
    trace = client.get(f"/agent/runs/{body['run_id']}/trace").json()
    ordinals = [e["ordinal"] for e in trace["entries"]]
    assert ordinals == sorted(ordinals)
    assert any(e["step_type"] == "tool_call" for e in trace["entries"])


def test_agent_run_reuses_supplied_conversation_id(client: TestClient):
    conversation_id = client.post("/conversations").json()["conversation_id"]
    resp = client.post(
        "/agent/run",
        json={"message": "hello", "conversation_id": conversation_id},
    )
    assert resp.status_code == 200
    assert resp.json()["conversation_id"] == conversation_id


# --- /agent/stream ----------------------------------------------------------------


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """Parse SSE frames into a list of (event_type, data) tuples."""
    events: list[tuple[str, dict]] = []
    event_type = None
    for line in text.splitlines():
        if line.startswith("event:"):
            event_type = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
            events.append((event_type, payload))
    return events


def test_agent_stream_ends_in_exactly_one_terminal_event(client: TestClient):
    _ingest(client)
    resp = client.post("/agent/stream", json={"message": "How does AgentForge answer?"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _parse_sse(resp.text)
    assert events, "expected at least one SSE event"

    types = [t for t, _ in events]
    terminal_types = [t for t in types if t in {"completion", "error"}]
    # Exactly one terminal event, and it is the last frame (Req 9.6, 9.9).
    assert terminal_types == ["completion"]
    assert types[-1] == "completion"

    # Monotonic sequences preserve production order end-to-end (Req 9.4).
    sequences = [data["sequence"] for _, data in events]
    assert sequences == list(range(len(events)))

    # The completion carries the answer and the single termination reason.
    _, completion = events[-1]
    assert completion["termination_reason"] in {"final-answer", "iteration-limit-reached"}
    assert completion["answer"]


def test_agent_stream_first_event_is_prompt_and_incremental(client: TestClient):
    """The first SSE event arrives well within 5s and events stream incrementally (Req 9.1, 9.2)."""
    _ingest(client)
    start = time.monotonic()
    first_event_at: float | None = None
    event_lines = 0
    with client.stream(
        "POST", "/agent/stream", json={"message": "How does AgentForge answer?"}
    ) as response:
        assert response.status_code == 200
        for line in response.iter_lines():
            if line.startswith("event:"):
                if first_event_at is None:
                    first_event_at = time.monotonic() - start
                event_lines += 1

    assert first_event_at is not None
    assert first_event_at < 5.0  # Req 9.1
    # More than one event was emitted (incremental steps + terminal), not a single blob.
    assert event_lines >= 2


# --- error envelope on unknown ids ------------------------------------------------


def test_unknown_run_trace_returns_404_envelope(client: TestClient):
    resp = client.get("/agent/runs/no-such-run/trace")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
