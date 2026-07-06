"""Unit tests for the four Integration_Tools (task 3.6).

Cover each tool's per-action ``input_schema`` shape (``additionalProperties: false`` and the
per-action required fields), the retrieval-by-id actions
(``gmail.read_message`` / ``google_drive.read_file`` / ``github.read_repo``), and each tool's
unique, stable name (Req 1.3, 12.1, 13.1, 13.4, 14.1, 14.4, 15.1, 15.4).
"""

from __future__ import annotations

from agentforge.integrations.github import GitHub_Tool, Mock_GitHub_Connector
from agentforge.integrations.gmail import Gmail_Tool, Mock_Gmail_Connector
from agentforge.integrations.google_drive import (
    Google_Drive_Tool,
    Mock_Google_Drive_Connector,
)
from agentforge.integrations.slack import Mock_Slack_Connector, Slack_Tool


def _required_for(schema: dict, action: str) -> set[str]:
    """Collect the fields required for ``action`` from top-level + conditional allOf blocks."""
    required = set(schema.get("required", []))
    for block in schema.get("allOf", []):
        const = block.get("if", {}).get("properties", {}).get("action", {}).get("const")
        if const == action:
            required.update(block.get("then", {}).get("required", []))
    return required


def _actions(schema: dict) -> list[str]:
    return schema["properties"]["action"]["enum"]


# --- schema shape: additionalProperties false + per-action required fields ---------


def test_slack_schema_shape():
    schema = Slack_Tool(
        Mock_Slack_Connector(), timeout_seconds=5.0, max_results=10
    ).input_schema
    assert schema["additionalProperties"] is False
    assert set(_actions(schema)) == {"read_channel", "post_message"}
    assert _required_for(schema, "read_channel") == {"action", "channel"}
    assert _required_for(schema, "post_message") == {"action", "channel", "text"}


def test_gmail_schema_shape():
    schema = Gmail_Tool(
        Mock_Gmail_Connector(), timeout_seconds=5.0, max_results=10
    ).input_schema
    assert schema["additionalProperties"] is False
    assert set(_actions(schema)) == {"search_messages", "read_message", "send_message"}
    assert _required_for(schema, "search_messages") == {"action", "query"}
    assert _required_for(schema, "read_message") == {"action", "message_id"}
    assert _required_for(schema, "send_message") == {"action", "to", "subject", "body"}


def test_google_drive_schema_shape():
    schema = Google_Drive_Tool(
        Mock_Google_Drive_Connector(), timeout_seconds=5.0, max_results=10
    ).input_schema
    assert schema["additionalProperties"] is False
    assert set(_actions(schema)) == {"list_files", "search_files", "read_file"}
    assert _required_for(schema, "list_files") == {"action"}
    assert _required_for(schema, "search_files") == {"action", "query"}
    assert _required_for(schema, "read_file") == {"action", "file_id"}
    # Read-only contract: no mutate/delete action is offered (Req 14.5).
    assert not ({"delete_file", "update_file", "create_file"} & set(_actions(schema)))


def test_github_schema_shape():
    schema = GitHub_Tool(
        Mock_GitHub_Connector(), timeout_seconds=5.0, max_results=10
    ).input_schema
    assert schema["additionalProperties"] is False
    assert set(_actions(schema)) == {
        "search_code",
        "search_issues",
        "read_repo",
        "create_issue",
    }
    assert _required_for(schema, "search_code") == {"action", "query"}
    assert _required_for(schema, "search_issues") == {"action", "query"}
    assert _required_for(schema, "read_repo") == {"action", "owner", "repo"}
    # ``body`` is optional for create_issue; only owner/repo/title are required (Req 15.1).
    assert _required_for(schema, "create_issue") == {"action", "owner", "repo", "title"}


# --- retrieval-by-id actions return the identified resource ------------------------


def test_gmail_read_message_returns_identified_message():
    connector = Mock_Gmail_Connector(message={"message_id": "m-42", "subject": "hi"})
    tool = Gmail_Tool(connector, timeout_seconds=5.0, max_results=10)

    result = tool.invoke({"action": "read_message", "message_id": "m-42"})

    assert result.ok is True
    assert result.data["message"]["message_id"] == "m-42"
    assert connector.calls == [("read_message", {"message_id": "m-42"})]


def test_google_drive_read_file_returns_identified_file():
    connector = Mock_Google_Drive_Connector(file={"file_id": "f-7", "name": "spec.md"})
    tool = Google_Drive_Tool(connector, timeout_seconds=5.0, max_results=10)

    result = tool.invoke({"action": "read_file", "file_id": "f-7"})

    assert result.ok is True
    assert result.data["file"]["file_id"] == "f-7"
    assert connector.calls == [("read_file", {"file_id": "f-7"})]


def test_github_read_repo_returns_identified_repo():
    connector = Mock_GitHub_Connector(repo={"owner": "acme", "repo": "widgets"})
    tool = GitHub_Tool(connector, timeout_seconds=5.0, max_results=10)

    result = tool.invoke({"action": "read_repo", "owner": "acme", "repo": "widgets"})

    assert result.ok is True
    assert result.data["repo"]["owner"] == "acme"
    assert result.data["repo"]["repo"] == "widgets"
    assert connector.calls == [("read_repo", {"owner": "acme", "repo": "widgets"})]


# --- unique, stable names ----------------------------------------------------------


def test_tool_names_are_unique_and_stable():
    names = [
        Slack_Tool(Mock_Slack_Connector(), timeout_seconds=5.0, max_results=10).name,
        Gmail_Tool(Mock_Gmail_Connector(), timeout_seconds=5.0, max_results=10).name,
        Google_Drive_Tool(
            Mock_Google_Drive_Connector(), timeout_seconds=5.0, max_results=10
        ).name,
        GitHub_Tool(Mock_GitHub_Connector(), timeout_seconds=5.0, max_results=10).name,
    ]
    assert names == ["slack", "gmail", "google_drive", "github"]
    assert len(set(names)) == len(names)
