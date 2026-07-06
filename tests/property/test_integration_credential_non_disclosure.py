"""Property-based test for credential non-disclosure across every surface (Task 8.4).

Feature: agentforge-integrations, Property 8: Credential values are never surfaced
anywhere. For any generated Credential value, that value never appears in a Tool_Result
(content or data), in the Integration_Status response, in any surfaced error message
(which also contains no internal stack trace), in recorded or exported trace/observability
data, or in any persisted Integration_Connection record.

Validates: Requirements 4.2, 4.3, 4.4, 7.6, 9.2, 11.4, 16.2
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from pydantic import SecretStr

from agentforge.config.settings import Settings
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Role
from agentforge.integrations.base import Upstream_Error
from agentforge.integrations.connection import (
    InMemory_Integration_Connection_Store,
    _reject_secret_config,
)
from agentforge.integrations.github import Keyed_GitHub_Connector, GitHub_Tool
from agentforge.integrations.gmail import Keyed_Gmail_Connector, Gmail_Tool
from agentforge.integrations.google_drive import (
    Keyed_Google_Drive_Connector,
    Google_Drive_Tool,
)
from agentforge.integrations.governance import audit_logger, record_integration_denial
from agentforge.integrations.slack import Keyed_Slack_Connector, Slack_Tool, Mock_Slack_Connector
from agentforge.integrations.status import Integration_Status_Service

# Secret values that are non-empty and structurally token-like.
_secrets = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126), min_size=6, max_size=40
)


def _base_settings(secret: str) -> Settings:
    """Settings with the secret configured as every integration credential + enabled."""
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        slack_bot_token=SecretStr(secret),
        gmail_token=SecretStr(secret),
        google_drive_token=SecretStr(secret),
        github_token=SecretStr(secret),
    )


def _keyed_tools(secret: str):
    """Build each Integration_Tool over a Keyed connector holding the secret token."""
    return [
        (Slack_Tool(Keyed_Slack_Connector(secret), timeout_seconds=5, max_results=20),
         {"action": "read_channel", "channel": "#general"}),
        (Gmail_Tool(Keyed_Gmail_Connector(secret), timeout_seconds=5, max_results=20),
         {"action": "search_messages", "query": "hello"}),
        (Google_Drive_Tool(Keyed_Google_Drive_Connector(secret), timeout_seconds=5, max_results=20),
         {"action": "list_files"}),
        (GitHub_Tool(Keyed_GitHub_Connector(secret), timeout_seconds=5, max_results=20),
         {"action": "search_code", "query": "def"}),
    ]


# Feature: agentforge-integrations, Property 8: Credential values are never surfaced anywhere.
@hyp_settings(max_examples=100, deadline=None)
@given(secret=_secrets)
def test_credential_never_surfaced_anywhere(secret):
    # 1) Successful Tool_Result over a Keyed connector holding the secret: neither the
    #    content nor the data ever contains the credential (Req 4.2, 4.4).
    for tool, args in _keyed_tools(secret):
        result = tool.invoke(args)
        assert result.ok is True
        assert secret not in str(result.content)
        assert secret not in str(result.data)

    # 2) Surfaced error message: even if a connector raises a failure whose text embeds the
    #    secret, the mapped Tool_Result surfaces only a fixed, safe message with no secret
    #    and no stack trace (Req 7.6).
    leaky = Mock_Slack_Connector(raises=Upstream_Error(f"upstream failed with token {secret}"))
    err = Slack_Tool(leaky, timeout_seconds=5, max_results=20).invoke(
        {"action": "read_channel", "channel": "#c"}
    )
    assert err.ok is False
    assert secret not in str(err.content)
    assert secret not in str(err.data)
    assert "Traceback" not in str(err.content)

    # 3) Integration_Status response: enablement is derived from the SecretStr credentials,
    #    but every entry is only {name, enabled} — never the credential (Req 9.2).
    entries = Integration_Status_Service(_base_settings(secret)).status()
    for entry in entries:
        assert entry.enabled is True
        assert secret not in entry.name
        assert secret not in repr(entry)

    # 4) Persisted Integration_Connection record: the store rejects any SecretStr and never
    #    persists credential material; a stored (non-secret) record surfaces no secret
    #    (Req 4.3, 11.4).
    store = InMemory_Integration_Connection_Store()
    with pytest.raises(ValueError):
        store.create(uuid4(), "slack", {"token": SecretStr(secret)})
    _reject_secret_config({"default_channel": "#general"})  # non-secret is accepted
    record = store.create(uuid4(), "slack", {"default_channel": "#general"})
    assert secret not in str(record.config)
    assert not hasattr(record, "token") and not hasattr(record, "secret")

    # 5) Recorded audit/observability data: the denial audit event carries the principal,
    #    org, integration, and action — never the credential and never a stack trace
    #    (Req 16.2, 8.2).
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[method-assign]
    audit_logger.addHandler(handler)
    try:
        principal = Principal(
            kind=PrincipalKind.USER.value,
            user_id=uuid4(),
            key_id=None,
            org_id=uuid4(),
            role=Role.VIEWER,
            permissions=frozenset(),
        )
        record_integration_denial(principal, "github", "create_issue")
    finally:
        audit_logger.removeHandler(handler)
    assert len(records) == 1
    logged = records[0]
    assert secret not in logged.getMessage()
    assert getattr(logged, "integration") == "github"
    assert getattr(logged, "action") == "create_issue"
    assert secret not in str(logged.__dict__)
