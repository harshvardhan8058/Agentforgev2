"""Unit tests for Tracing_Exporter selection and the keyless no-call guarantee (Task 3.3).

Assert ``build_tracing_exporter`` returns ``NoOp_Tracing_Exporter`` with no credential and
``LangSmith_Tracing_Exporter`` with one; assert ``NoOp.export`` makes no external call
(Req 1.2, 1.3, 1.4, 11.2).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from agentforge.observability.tracing_exporter import (
    LangSmith_Tracing_Exporter,
    NoOp_Tracing_Exporter,
    build_tracing_exporter,
)
from agentforge.tracing.base import Trace
from tests.conftest import apply_base_env


def _load(monkeypatch, **env):
    apply_base_env(monkeypatch)
    for key in ("LANGSMITH_API_KEY", "TRACING_EXPORT_ENABLED"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from agentforge.config.settings import load_settings

    return load_settings()


def test_no_credential_selects_noop(monkeypatch):
    settings = _load(monkeypatch)
    exporter = build_tracing_exporter(settings)
    assert isinstance(exporter, NoOp_Tracing_Exporter)
    assert exporter.name == "noop"


def test_credential_selects_langsmith(monkeypatch):
    settings = _load(monkeypatch, LANGSMITH_API_KEY="ls-secret")
    exporter = build_tracing_exporter(settings)
    assert isinstance(exporter, LangSmith_Tracing_Exporter)
    assert exporter.name == "langsmith"


def test_disabled_toggle_forces_noop(monkeypatch):
    settings = _load(monkeypatch, LANGSMITH_API_KEY="ls-secret", TRACING_EXPORT_ENABLED="false")
    assert isinstance(build_tracing_exporter(settings), NoOp_Tracing_Exporter)


def test_noop_export_makes_no_external_call(monkeypatch):
    """A network-guard spy proves NoOp export never touches the network (Req 1.3, 11.2)."""
    import socket

    def _guard(*args, **kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("NoOp_Tracing_Exporter must not make any external call")

    monkeypatch.setattr(socket.socket, "connect", _guard)

    exporter = NoOp_Tracing_Exporter()
    assert exporter.export(Trace(run_id="r"), org_id=uuid4(), user_id=None) is None


def test_langsmith_export_swallows_client_construction_failure(monkeypatch):
    """With no injected client and no real dep available, export still never raises."""
    exporter = LangSmith_Tracing_Exporter("k", project="p")
    # No langsmith package installed on the keyless path -> import/construct fails ->
    # suppressed by the export guard (Req 1.7).
    assert exporter.export(Trace(run_id="r"), org_id=uuid4(), user_id=None) is None


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__])
