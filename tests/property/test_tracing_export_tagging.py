"""Property-based test for tracing-export org/user tagging (Task 3.1).

Feature: agentforge-observability, Property 1: Tracing export tags the trace with org and
user. For any Trace, any org_id, and any user_id (present or absent), when the active
Tracing_Exporter exports that trace, the payload delivered to the external destination is
tagged with exactly that org_id and user_id.

Validates: Requirements 1.5
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.observability.tracing_exporter import LangSmith_Tracing_Exporter
from agentforge.tracing.base import Trace, Trace_Entry


class _CapturingClient:
    """Fake LangSmith client recording the kwargs passed to ``create_run``."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create_run(self, **kwargs) -> None:
        self.calls.append(kwargs)


_entries = st.lists(
    st.builds(
        Trace_Entry,
        run_id=st.text(min_size=1, max_size=12),
        ordinal=st.integers(min_value=0, max_value=50),
        step_type=st.sampled_from(["reason", "tool_call", "observe"]),
        tool_name=st.none() | st.text(max_size=12),
        outcome=st.none() | st.text(max_size=12),
    ),
    max_size=6,
)
_traces = st.builds(Trace, run_id=st.text(min_size=1, max_size=12), entries=_entries)


# Feature: agentforge-observability, Property 1: Tracing export tags the trace with org
# and user.
@hyp_settings(max_examples=100, deadline=None)
@given(trace=_traces, org_id=st.uuids(), user_id=st.none() | st.uuids())
def test_export_tags_trace_with_org_and_user(trace, org_id, user_id):
    client = _CapturingClient()
    exporter = LangSmith_Tracing_Exporter("ls-key", project="proj", client=client)

    exporter.export(trace, org_id=org_id, user_id=user_id)

    assert len(client.calls) == 1
    metadata = client.calls[0]["extra"]["metadata"]
    assert metadata["org_id"] == str(org_id)
    assert metadata["user_id"] == (str(user_id) if user_id is not None else None)
