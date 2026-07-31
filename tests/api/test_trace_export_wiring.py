"""API tests: every run path actually exports its trace (Req 10.2).

Before this, the Tracing_Exporter seam had no caller in ``src/`` at all — configuring
LangSmith exported nothing. Unit tests on the exporter and on the export service cannot
catch that class of defect: the seam was *correct*, it was simply never reached. These
tests therefore assert at the transport layer, through the real app, that a finished run
reaches the exporter — one test per path, because each path attaches the export differently:

* ``POST /agent/run`` — a FastAPI background task (runs after the response is sent);
* ``POST /agent/stream`` — the streaming service's completion hook (runs after the single
  terminal event has been delivered);
* ``POST /multi-agent/runs`` — a background task;
* ``POST /multi-agent/runs/{id}/stream`` — after the service's frames are exhausted.

Plus the two guarantees that make calling an exporter from a run path acceptable at all:
a broken exporter cannot change a run's result, and it cannot break the SSE
single-terminal contract.

``TestClient`` runs background tasks synchronously as part of the request, so the
assertions can read the capture immediately after the call returns.
"""

from __future__ import annotations

import json
import uuid

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
from agentforge.observability.trace_export import Trace_Export_Service
from agentforge.observability.tracing_exporter import Tracing_Exporter
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.base import Trace
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


class _CapturingExporter(Tracing_Exporter):
    """A credentialed-looking exporter that records what it received."""

    def __init__(self, name: str = "capturing") -> None:
        self._name = name
        self.calls: list[tuple[Trace, uuid.UUID, uuid.UUID | None]] = []

    @property
    def name(self) -> str:
        return self._name

    def export(self, trace, *, org_id, user_id) -> None:
        self.calls.append((trace, org_id, user_id))


class _RaisingExporter(_CapturingExporter):
    """Breaks the seam's "never propagate" contract, to prove runs survive it."""

    def export(self, trace, *, org_id, user_id) -> None:
        raise RuntimeError("exporter is broken")


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


def _wire(exporter: Tracing_Exporter) -> tuple[TestClient, _CapturingExporter, uuid.UUID]:
    """Build the real app with keyless doubles and ``exporter`` behind the export service."""
    settings = _make_settings()
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    recorder = InMemory_Trace_Recorder()
    agent_ctx = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=recorder,
    )
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = build_multi_agent_context(
        settings, agent=agent_ctx
    )
    # The composition root hands the agentic recorder to the observability graph; the same
    # wiring is exercised here rather than injecting a pre-built service, so a regression in
    # that hand-off is visible.
    app.state.observability_context = build_observability_context(
        settings, app=app_ctx, trace_recorder=recorder, tracing_exporter=exporter
    )
    headers, org_id, _ctx = install_enterprise_auth(app, settings)
    return (
        TestClient(app, headers=headers, raise_server_exceptions=False),
        exporter,
        org_id,
    )


@pytest.fixture
def wired():
    return _wire(_CapturingExporter())


def _terminal_events(text: str) -> list[dict]:
    """Return the parsed terminal (completion/error) SSE events in a stream body."""
    events: list[dict] = []
    for block in text.split("\n\n"):
        event_type = None
        data = None
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = line.split(":", 1)[1].strip()
        if event_type in {"completion", "error"} and data is not None:
            events.append({"type": event_type, "data": json.loads(data)})
    return events


# --- single agent -----------------------------------------------------------------


def test_agent_run_exports_the_completed_trace(wired):
    client, exporter, org_id = wired

    resp = client.post("/agent/run", json={"message": "what is agentforge?"})

    assert resp.status_code == 200
    run_id = resp.json()["run_id"]
    assert len(exporter.calls) == 1
    trace, exported_org, exported_user = exporter.calls[0]
    assert trace.run_id == run_id
    assert trace.entries, "an exported trace must carry the run's steps"
    assert exported_org == org_id
    # A user principal exports its user_id; the enterprise helper installs a user token.
    assert exported_user is not None


def test_agent_stream_exports_after_the_terminal_event(wired):
    client, exporter, org_id = wired

    with client.stream("POST", "/agent/stream", json={"message": "hello"}) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    terminals = _terminal_events(body)
    assert len(terminals) == 1, "the single-terminal guarantee must still hold"
    assert terminals[0]["type"] == "completion"
    assert len(exporter.calls) == 1
    assert exporter.calls[0][0].run_id == terminals[0]["data"]["run_id"]
    assert exporter.calls[0][1] == org_id


def test_a_broken_exporter_cannot_fail_a_run():
    client, _exporter, _org = _wire(_RaisingExporter())

    resp = client.post("/agent/run", json={"message": "what is agentforge?"})

    assert resp.status_code == 200
    assert resp.json()["answer"]
    assert resp.json()["termination_reason"]


def test_a_broken_exporter_cannot_break_the_single_terminal_guarantee():
    client, _exporter, _org = _wire(_RaisingExporter())

    with client.stream("POST", "/agent/stream", json={"message": "hello"}) as response:
        body = "".join(response.iter_text())

    terminals = _terminal_events(body)
    assert [t["type"] for t in terminals] == ["completion"]


def test_the_keyless_default_exports_nothing_but_still_records():
    """No credential ⇒ NoOp exporter ⇒ nothing leaves the process, traces still served."""
    settings = _make_settings()
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    recorder = InMemory_Trace_Recorder()
    agent_ctx = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=recorder,
    )
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.observability_context = build_observability_context(
        settings, app=app_ctx, trace_recorder=recorder
    )
    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    client = TestClient(app, headers=headers, raise_server_exceptions=False)

    service: Trace_Export_Service = app.state.observability_context.trace_export_service
    assert service.enabled is False
    assert service.exporter_name == "noop"

    run_id = client.post("/agent/run", json={"message": "hello"}).json()["run_id"]
    # The trace itself is still recorded and served — only export is off.
    assert client.get(f"/agent/runs/{run_id}/trace").status_code == 200


def test_run_endpoints_work_without_an_observability_context():
    """An observability concern must never be able to fail the work it observes."""
    settings = _make_settings()
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    # Deliberately no observability_context on app.state.
    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    client = TestClient(app, headers=headers, raise_server_exceptions=False)

    assert client.post("/agent/run", json={"message": "hello"}).status_code == 200


# --- multi-agent ------------------------------------------------------------------


def test_multi_agent_run_exports_the_completed_trace(wired):
    client, exporter, org_id = wired

    resp = client.post("/multi-agent/runs", json={"task": "summarize the corpus"})

    assert resp.status_code == 201
    run_id = resp.json()["run_id"]
    assert [call[0].run_id for call in exporter.calls] == [run_id]
    assert exporter.calls[0][1] == org_id
    # The multi-agent trace carries per-role attribution, which must survive the export.
    assert exporter.calls[0][0].entries


def test_multi_agent_stream_exports_after_the_stream_completes(wired):
    client, exporter, _org = wired
    run_id = client.post("/multi-agent/runs", json={"task": "plan a launch"}).json()[
        "run_id"
    ]
    exported_by_start = len(exporter.calls)

    with client.stream("POST", f"/multi-agent/runs/{run_id}/stream") as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert body, "the stream must have produced frames"
    assert len(exporter.calls) == exported_by_start + 1
    assert exporter.calls[-1][0].run_id == run_id
