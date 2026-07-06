"""Property-based test for single-write dispatch and Drive read-only (Property 7)."""

from __future__ import annotations

import string

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.integrations.github import GitHub_Tool, Mock_GitHub_Connector
from agentforge.integrations.gmail import Gmail_Tool, Mock_Gmail_Connector
from agentforge.integrations.google_drive import (
    Google_Drive_Tool,
    Mock_Google_Drive_Connector,
)
from agentforge.integrations.slack import Mock_Slack_Connector, Slack_Tool

# Non-empty text so validated arguments are realistic; the alphabet is unremarkable.
_text = st.text(
    alphabet=string.ascii_letters + string.digits + " #-_.@", min_size=1, max_size=24
)

# Any connector operation whose name implies a mutation. The Google Drive contract exposes
# none of these — it is read-only — so a Drive invocation must never call one (Req 14.5).
_WRITE_OP_NAMES = {"create", "update", "delete", "mutate", "write", "remove", "post"}
_DRIVE_ACTIONS = ("list_files", "search_files", "read_file")
_WRITE_KINDS = ("slack", "gmail", "github")


# Feature: agentforge-integrations, Property 7: A write action performs exactly one connector
# write and no other side effect (and any Google Drive action performs zero write/mutate/delete).
@hyp_settings(max_examples=150, deadline=None)
@given(
    kind=st.sampled_from(_WRITE_KINDS + _DRIVE_ACTIONS),
    a=_text,
    b=_text,
    c=_text,
    d=_text,
)
def test_single_write_and_drive_is_read_only(kind, a, b, c, d):
    """Feature: agentforge-integrations, Property 7: For any write action
    (slack.post_message, gmail.send_message, github.create_issue) with validated arguments,
    invoke makes exactly one call to the corresponding connector write operation with those
    arguments and makes no other connector call; and for any Google Drive action, invoke
    makes zero write/mutate/delete calls (the Drive connector exposes only read operations).

    Validates: Requirements 6.5, 12.5, 13.5, 15.5, 14.5
    """
    if kind == "slack":
        connector = Mock_Slack_Connector()
        tool = Slack_Tool(connector, timeout_seconds=5.0, max_results=10)
        result = tool.invoke({"action": "post_message", "channel": a, "text": b})
        assert result.ok is True
        # Exactly one write call with the validated arguments, and no other call.
        assert connector.calls == [("post_message", {"channel": a, "text": b})]
        return

    if kind == "gmail":
        connector = Mock_Gmail_Connector()
        tool = Gmail_Tool(connector, timeout_seconds=5.0, max_results=10)
        result = tool.invoke(
            {"action": "send_message", "to": a, "subject": b, "body": c}
        )
        assert result.ok is True
        assert connector.calls == [
            ("send_message", {"to": a, "subject": b, "body": c})
        ]
        return

    if kind == "github":
        connector = Mock_GitHub_Connector()
        tool = GitHub_Tool(connector, timeout_seconds=5.0, max_results=10)
        result = tool.invoke(
            {"action": "create_issue", "owner": a, "repo": b, "title": c, "body": d}
        )
        assert result.ok is True
        assert connector.calls == [
            ("create_issue", {"owner": a, "repo": b, "title": c, "body": d})
        ]
        return

    # Google Drive: any action performs zero write/mutate/delete calls (Req 14.5).
    connector = Mock_Google_Drive_Connector(
        files=[{"file_id": "f-1"}], file={"file_id": "f-1"}
    )
    tool = Google_Drive_Tool(connector, timeout_seconds=5.0, max_results=10)
    arguments: dict = {"action": kind}
    if kind == "search_files":
        arguments["query"] = a
    elif kind == "read_file":
        arguments["file_id"] = a
    result = tool.invoke(arguments)

    assert result.ok is True
    assert all(op_name not in _WRITE_OP_NAMES for op_name, _ in connector.calls)
    # A single read op is performed and it is one of the read-only actions.
    assert len(connector.calls) == 1
    assert connector.calls[0][0] in _DRIVE_ACTIONS
