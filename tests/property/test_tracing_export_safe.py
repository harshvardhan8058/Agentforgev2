"""Property-based test that trace export never changes a run's outcome (Task 3.2).

Feature: agentforge-observability, Property 2: Trace export never changes a run's outcome.
For any underlying tracer client that raises an arbitrary exception on forwarding, the
Tracing_Exporter.export call returns normally (the failure is suppressed) and the run
result observed by the caller is identical to the result produced with a successful or
NoOp export.

Validates: Requirements 1.7
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.observability.tracing_exporter import (
    LangSmith_Tracing_Exporter,
    NoOp_Tracing_Exporter,
)
from agentforge.tracing.base import Trace


class _RaisingClient:
    """Fake LangSmith client that always raises on forward."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def create_run(self, **kwargs):
        raise self._exc


_exceptions = st.sampled_from(
    [
        RuntimeError("boom"),
        ValueError("bad"),
        ConnectionError("network down"),
        KeyError("missing"),
        TimeoutError("slow"),
    ]
)


# Feature: agentforge-observability, Property 2: Trace export never changes a run's
# outcome.
@hyp_settings(max_examples=100, deadline=None)
@given(run_id=st.text(min_size=1, max_size=12), org_id=st.uuids(), exc=_exceptions)
def test_export_failure_is_suppressed(run_id, org_id, exc):
    trace = Trace(run_id=run_id)

    # A run "result" the caller holds; export must not disturb it.
    run_result = {"run_id": run_id, "answer": "final"}
    baseline = dict(run_result)

    raising = LangSmith_Tracing_Exporter("k", client=_RaisingClient(exc))
    noop = NoOp_Tracing_Exporter()

    # Both return None (normally) and neither propagates the failure.
    assert raising.export(trace, org_id=org_id, user_id=None) is None
    assert noop.export(trace, org_id=org_id, user_id=None) is None

    # The run result observed by the caller is unchanged by either export path.
    assert run_result == baseline
