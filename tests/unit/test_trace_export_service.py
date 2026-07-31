"""Unit tests for the Trace_Export_Service — the link that made trace export real.

The ``Tracing_Exporter`` seam shipped in Phase 6 with a NoOp implementation, a LangSmith
implementation, a settings-driven factory, a DI accessor and its own tests — and no caller
anywhere in ``src/``. Setting ``LANGSMITH_API_KEY`` changed a log line and nothing else.
This service is what a completed run now goes through, so these tests pin the four
properties that make it safe to call from a run path:

1. **Off means off, cheaply.** With the NoOp exporter nothing is exported and the trace
   store is never even read — the keyless default must not pay for a feature it does not
   use, and ``enabled`` must not claim otherwise.
2. **A failure anywhere is swallowed.** A recorder that raises, an exporter that raises
   (breaking its own contract), a trace that does not exist: all return ``False`` and none
   propagate, because the run is already finished and its result already delivered.
3. **What is exported is what the API would serve** — the recorder's trace, tagged with the
   caller's ``org_id``/``user_id``.
4. **Nothing is exported for an empty or cross-tenant trace**, since the recorder returns
   an empty trace for an unknown run, a cross-tenant run, and a step-free run alike.
"""

from __future__ import annotations

import uuid

import pytest

from agentforge.observability.trace_export import (
    Trace_Export_Service,
    disabled_trace_export_service,
)
from agentforge.observability.tracing_exporter import (
    NoOp_Tracing_Exporter,
    Tracing_Exporter,
)
from agentforge.tracing.base import Trace
from agentforge.tracing.recorder import InMemory_Trace_Recorder

ORG = uuid.uuid4()
USER = uuid.uuid4()


class _CapturingExporter(Tracing_Exporter):
    """Records what it was asked to export; stands in for LangSmith/OTLP."""

    def __init__(self, name: str = "capturing") -> None:
        self._name = name
        self.calls: list[tuple[Trace, uuid.UUID, uuid.UUID | None]] = []

    @property
    def name(self) -> str:
        return self._name

    def export(self, trace, *, org_id, user_id) -> None:
        self.calls.append((trace, org_id, user_id))


class _RaisingExporter(_CapturingExporter):
    """An exporter that breaks the seam's own "never propagate" contract."""

    def export(self, trace, *, org_id, user_id) -> None:
        raise RuntimeError("exporter is broken")


class _CountingRecorder(InMemory_Trace_Recorder):
    """In-memory recorder that counts reads, to prove the NoOp path never reads."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def get_trace(self, org_id, run_id):
        self.reads += 1
        return super().get_trace(org_id, run_id)


class _FailingRecorder(InMemory_Trace_Recorder):
    def get_trace(self, org_id, run_id):
        raise RuntimeError("trace store is unavailable")


def _recorded(recorder: InMemory_Trace_Recorder, run_id: str, steps: int = 2) -> None:
    for index in range(steps):
        recorder.record(
            ORG,
            run_id,
            "reason" if index % 2 == 0 else "tool_call",
            tool_name=None if index % 2 == 0 else "rag_search",
            outcome=None if index % 2 == 0 else "ok",
        )


# --- off means off ----------------------------------------------------------------


def test_noop_exporter_disables_export_without_reading_the_trace_store():
    recorder = _CountingRecorder()
    _recorded(recorder, "run-1")
    service = Trace_Export_Service(NoOp_Tracing_Exporter(), recorder)

    assert service.enabled is False
    assert service.exporter_name == "noop"
    assert service.export_run("run-1", org_id=ORG, user_id=USER) is False
    # The short-circuit is the point: no store round trip per run when export is off.
    assert recorder.reads == 0


def test_a_configured_exporter_without_a_recorder_is_reported_as_disabled():
    """Claiming export is on while nothing can be read would be the original defect again."""
    service = Trace_Export_Service(_CapturingExporter(), None)

    assert service.exporter_name == "capturing"
    assert service.enabled is False
    assert service.export_run("run-1", org_id=ORG, user_id=USER) is False


def test_the_disabled_service_is_shared_and_inert():
    first = disabled_trace_export_service()
    assert first is disabled_trace_export_service()
    assert first.enabled is False
    assert first.export_run("run-1", org_id=ORG, user_id=USER) is False


# --- the happy path ---------------------------------------------------------------


def test_a_recorded_run_is_exported_with_its_tenant_and_user():
    recorder = InMemory_Trace_Recorder()
    _recorded(recorder, "run-1", steps=3)
    exporter = _CapturingExporter()
    service = Trace_Export_Service(exporter, recorder)

    assert service.enabled is True
    assert service.export_run("run-1", org_id=ORG, user_id=USER) is True

    assert len(exporter.calls) == 1
    trace, org_id, user_id = exporter.calls[0]
    assert org_id == ORG
    assert user_id == USER
    # Exactly what GET /agent/runs/{id}/trace would serve: same entries, same order.
    assert trace.run_id == "run-1"
    assert [e.ordinal for e in trace.entries] == [0, 1, 2]
    assert [e.step_type for e in trace.entries] == ["reason", "tool_call", "reason"]


def test_user_id_is_optional_for_an_api_key_principal():
    recorder = InMemory_Trace_Recorder()
    _recorded(recorder, "run-1")
    exporter = _CapturingExporter()

    assert (
        Trace_Export_Service(exporter, recorder).export_run("run-1", org_id=ORG) is True
    )
    assert exporter.calls[0][2] is None


# --- nothing to export ------------------------------------------------------------


@pytest.mark.parametrize("other_org", [True, False])
def test_unknown_or_cross_tenant_run_exports_nothing(other_org: bool):
    recorder = InMemory_Trace_Recorder()
    _recorded(recorder, "run-1")
    exporter = _CapturingExporter()
    service = Trace_Export_Service(exporter, recorder)

    if other_org:
        assert service.export_run("run-1", org_id=uuid.uuid4()) is False
    else:
        assert service.export_run("does-not-exist", org_id=ORG) is False
    assert exporter.calls == []


# --- failures are absorbed --------------------------------------------------------


def test_a_failing_trace_store_does_not_propagate():
    exporter = _CapturingExporter()
    service = Trace_Export_Service(exporter, _FailingRecorder())

    assert service.export_run("run-1", org_id=ORG, user_id=USER) is False
    assert exporter.calls == []


def test_an_exporter_that_breaks_its_contract_does_not_propagate():
    recorder = InMemory_Trace_Recorder()
    _recorded(recorder, "run-1")
    service = Trace_Export_Service(_RaisingExporter(), recorder)

    assert service.export_run("run-1", org_id=ORG, user_id=USER) is False


def test_export_never_mutates_the_recorded_trace():
    """The API must serve the same trace after an export as before it."""
    recorder = InMemory_Trace_Recorder()
    _recorded(recorder, "run-1", steps=3)
    before = [
        (e.ordinal, e.step_type, e.tool_name, e.outcome)
        for e in recorder.get_trace(ORG, "run-1").entries
    ]

    Trace_Export_Service(_CapturingExporter(), recorder).export_run(
        "run-1", org_id=ORG, user_id=USER
    )

    after = [
        (e.ordinal, e.step_type, e.tool_name, e.outcome)
        for e in recorder.get_trace(ORG, "run-1").entries
    ]
    assert after == before
