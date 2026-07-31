"""API tests for ``GET /observability/status``.

The endpoint exists to remove an ambiguity a client could not otherwise resolve: a trace
view showing nothing might mean "this run had no steps" or "export is off", and traces are
always recorded while export depends on a credential. It reports what the process will
actually do, so these tests pin that it is derived from the wired export service rather than
from configuration, is gated on ``read``, and never carries a credential.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from agentforge.api.deps import get_current_principal
from agentforge.config.container import build_observability_context
from agentforge.config.settings import Settings
from agentforge.enterprise.models import Principal
from agentforge.enterprise.principal import PrincipalKind
from agentforge.enterprise.rbac import Role
from agentforge.main import create_app
from agentforge.observability.tracing_exporter import Tracing_Exporter
from agentforge.tracing.recorder import InMemory_Trace_Recorder

from tests.enterprise_helpers import install_enterprise_auth


class _NamedExporter(Tracing_Exporter):
    """A stand-in for a credentialed exporter, without needing its dependency."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    def export(self, trace, *, org_id, user_id) -> None:  # pragma: no cover - unused here
        return


def _make_settings(**overrides) -> Settings:
    base = dict(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )
    base.update(overrides)
    return Settings(**base)


def _app(settings: Settings, **observability_overrides):
    app = create_app(settings)
    app.state.settings = settings
    app.state.observability_context = build_observability_context(
        settings, **observability_overrides
    )
    headers, org_id, _ctx = install_enterprise_auth(app, settings)
    return TestClient(app, raise_server_exceptions=False), headers, org_id


@pytest.fixture
def keyless():
    return _app(_make_settings(), trace_recorder=InMemory_Trace_Recorder())


def test_requires_authentication(keyless):
    client, _headers, _org = keyless
    resp = client.get("/observability/status")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


def test_requires_read(keyless):
    client, headers, org_id = keyless
    app = client.app

    def _no_read() -> Principal:
        return Principal(
            kind=PrincipalKind.USER.value,
            user_id=uuid.uuid4(),
            key_id=None,
            org_id=org_id,
            role=Role.VIEWER,
            permissions=frozenset(),
        )

    app.dependency_overrides[get_current_principal] = _no_read
    try:
        resp = client.get("/observability/status", headers=headers)
    finally:
        app.dependency_overrides.pop(get_current_principal, None)
    assert resp.status_code == 403
    assert resp.json()["error"]["details"]["required"] == "read"


def test_keyless_default_reports_export_off(keyless):
    client, headers, _org = keyless

    body = client.get("/observability/status", headers=headers).json()

    assert body == {
        "trace_export": {"enabled": False, "exporter": "noop", "destination": None}
    }


def test_a_configured_exporter_reports_its_destination():
    settings = _make_settings(
        langsmith_api_key=SecretStr("not-a-real-key"), langsmith_project="acme-prod"
    )
    client, headers, _org = _app(settings, trace_recorder=InMemory_Trace_Recorder())

    body = client.get("/observability/status", headers=headers).json()

    assert body["trace_export"]["enabled"] is True
    assert body["trace_export"]["exporter"] == "langsmith"
    assert body["trace_export"]["destination"] == "acme-prod"
    # The credential itself must never appear.
    assert "not-a-real-key" not in client.get(
        "/observability/status", headers=headers
    ).text


def test_status_reflects_the_service_not_the_settings():
    """A credentialed exporter with no recorder exports nothing, and must say so.

    Reporting `enabled: true` from configuration alone would recreate the exact defect the
    export work fixed: a feature that looks configured and does nothing.
    """
    settings = _make_settings(langsmith_api_key=SecretStr("not-a-real-key"))
    # No trace_recorder passed -> the export service has nothing to read.
    client, headers, _org = _app(settings)

    body = client.get("/observability/status", headers=headers).json()

    assert body["trace_export"]["exporter"] == "langsmith"
    assert body["trace_export"]["enabled"] is False


def test_a_third_party_exporter_name_is_reported_verbatim():
    settings = _make_settings()
    client, headers, _org = _app(
        settings,
        trace_recorder=InMemory_Trace_Recorder(),
        tracing_exporter=_NamedExporter("otlp"),
    )

    body = client.get("/observability/status", headers=headers).json()

    assert body["trace_export"] == {
        "enabled": True,
        "exporter": "otlp",
        # `destination` is a LangSmith project label; another exporter has none to report.
        "destination": None,
    }
