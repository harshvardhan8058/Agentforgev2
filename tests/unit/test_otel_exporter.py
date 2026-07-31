"""Unit tests for the OTLP Tracing_Exporter.

LangSmith was the only destination a trace could reach, which tied the platform's
observability to one vendor. This exporter speaks OTLP, so any collector can receive
AgentForge traces. The tests pin what a second exporter behind the same seam must satisfy:

* the seam's hard contract — never raise, never require a credential to *construct*, and
  degrade to "no export" when its optional dependency is missing;
* the mapping — one span per run with one child per trace entry, carrying the structural
  attributes the console timeline shows;
* the privacy boundary — the ``detail`` payload can hold prompt/observation text and must
  **not** be exported; ``role_id`` is the single forwarded key, because it is multi-agent
  attribution rather than content;
* selection — an OTLP endpoint activates it, LangSmith keeps precedence when both are
  configured, and the keyless default is untouched.

The span assertions run against the real OpenTelemetry SDK with an in-memory span
exporter injected, so they check actual SDK behaviour rather than a hand-rolled double. The
SDK is an optional extra, so they skip (rather than fail) where it is absent.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr

from agentforge.config.settings import Settings
from agentforge.observability.otel_exporter import (
    OTLP_EXPORTER_NAME,
    OTLP_Tracing_Exporter,
)
from agentforge.observability.tracing_exporter import (
    LangSmith_Tracing_Exporter,
    NoOp_Tracing_Exporter,
    build_tracing_exporter,
)
from agentforge.tracing.base import Trace, Trace_Entry

ORG = uuid.uuid4()
USER = uuid.uuid4()

pytest_plugins: list[str] = []


def _settings(**overrides) -> Settings:
    base = dict(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
    )
    base.update(overrides)
    return Settings(**base)


def _trace() -> Trace:
    return Trace(
        run_id="run-1",
        entries=[
            Trace_Entry(run_id="run-1", ordinal=0, step_type="reason"),
            Trace_Entry(
                run_id="run-1",
                ordinal=1,
                step_type="tool_call",
                tool_name="rag_search",
                outcome="ok",
                # `detail` carries content plus the one attribution key.
                detail={"role_id": "researcher", "prompt": "SECRET PROMPT TEXT"},
            ),
        ],
    )


def _in_memory_exporter():
    """Return an OTel in-memory SpanExporter, skipping the test if the SDK is absent."""
    module = pytest.importorskip(
        "opentelemetry.sdk.trace.export.in_memory_span_exporter",
        reason="the OpenTelemetry SDK is an optional extra ('otel')",
    )
    return module.InMemorySpanExporter()


# --- selection --------------------------------------------------------------------


def test_keyless_default_is_unchanged():
    assert isinstance(build_tracing_exporter(_settings()), NoOp_Tracing_Exporter)


def test_an_otlp_endpoint_selects_the_otlp_exporter():
    settings = _settings(otel_exporter_endpoint="http://collector:4318/v1/traces")

    assert settings.active_tracing_exporter() == OTLP_EXPORTER_NAME
    exporter = build_tracing_exporter(settings)
    assert isinstance(exporter, OTLP_Tracing_Exporter)
    assert exporter.name == "otlp"


def test_langsmith_keeps_precedence_when_both_are_configured():
    """A deployment already exporting to LangSmith must not be silently re-pointed."""
    settings = _settings(
        langsmith_api_key=SecretStr("not-a-real-key"),
        otel_exporter_endpoint="http://collector:4318/v1/traces",
    )

    assert settings.active_tracing_exporter() == "langsmith"
    assert isinstance(build_tracing_exporter(settings), LangSmith_Tracing_Exporter)


def test_disabling_export_beats_every_destination():
    settings = _settings(
        otel_exporter_endpoint="http://collector:4318/v1/traces",
        tracing_export_enabled=False,
    )

    assert settings.active_tracing_exporter() == "noop"
    assert isinstance(build_tracing_exporter(settings), NoOp_Tracing_Exporter)


def test_a_blank_endpoint_means_unset():
    """An empty env var must not select an exporter pointing nowhere."""
    settings = _settings(otel_exporter_endpoint="   ")

    assert settings.otel_exporter_endpoint is None
    assert settings.active_tracing_exporter() == "noop"


def test_otel_headers_are_redacted():
    settings = _settings(
        otel_exporter_endpoint="http://collector:4318/v1/traces",
        otel_headers=SecretStr("x-api-key=super-secret"),
    )

    assert "super-secret" not in repr(settings)
    assert "super-secret" not in str(settings)
    assert "super-secret" not in str(settings.model_dump())


# --- the seam's contract ----------------------------------------------------------


def test_construction_makes_no_network_call_and_export_never_raises(monkeypatch):
    """Constructing an exporter must not touch the network (keyless boot invariant)."""
    import socket

    def _no_network(*_args, **_kwargs):  # pragma: no cover - must never be reached
        raise AssertionError("export must not open a socket in this test")

    monkeypatch.setattr(socket.socket, "connect", _no_network)

    exporter = OTLP_Tracing_Exporter("http://collector:4318/v1/traces")
    # No SDK call has happened yet, so nothing was constructed at __init__ time.
    assert exporter.name == "otlp"
    # With the OTLP/HTTP exporter absent from the environment this degrades silently; with
    # it present, the BatchSpanProcessor queues without connecting. Either way: no raise.
    assert exporter.export(_trace(), org_id=ORG, user_id=USER) is None


def test_export_swallows_a_missing_dependency(monkeypatch):
    """A configured endpoint without the extra installed must not fail a run."""
    import builtins

    real_import = builtins.__import__

    def _fail_otel(name, *args, **kwargs):
        if name.startswith("opentelemetry"):
            raise ImportError(f"no module named {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_otel)

    exporter = OTLP_Tracing_Exporter("http://collector:4318/v1/traces")
    assert exporter.export(_trace(), org_id=ORG, user_id=USER) is None


def test_export_swallows_a_failing_span_exporter():
    class _Boom:
        def export(self, *_args, **_kwargs):
            raise RuntimeError("collector is down")

        def shutdown(self):
            return None

        def force_flush(self, *_args, **_kwargs):
            return True

    exporter = OTLP_Tracing_Exporter("http://collector:4318", span_exporter=_Boom())
    assert exporter.export(_trace(), org_id=ORG, user_id=USER) is None


# --- the mapping ------------------------------------------------------------------


def test_a_trace_becomes_a_run_span_with_one_child_per_entry():
    sink = _in_memory_exporter()
    exporter = OTLP_Tracing_Exporter(
        "http://collector:4318", service_name="agentforge-test", span_exporter=sink
    )

    exporter.export(_trace(), org_id=ORG, user_id=USER)

    spans = sink.get_finished_spans()
    names = [span.name for span in spans]
    assert "agent.run" in names
    assert names.count("agent.reason") == 1
    assert names.count("agent.tool_call") == 1

    run_span = next(span for span in spans if span.name == "agent.run")
    assert run_span.attributes["agentforge.run_id"] == "run-1"
    assert run_span.attributes["agentforge.org_id"] == str(ORG)
    assert run_span.attributes["agentforge.user_id"] == str(USER)
    assert run_span.attributes["agentforge.step_count"] == 2
    assert run_span.resource.attributes["service.name"] == "agentforge-test"

    tool_span = next(span for span in spans if span.name == "agent.tool_call")
    assert tool_span.attributes["agentforge.ordinal"] == 1
    assert tool_span.attributes["agentforge.tool_name"] == "rag_search"
    assert tool_span.attributes["agentforge.outcome"] == "ok"
    # Multi-agent attribution is forwarded...
    assert tool_span.attributes["agentforge.role_id"] == "researcher"
    # ...but the step spans are children of the run span, not siblings.
    assert tool_span.parent is not None
    assert tool_span.parent.span_id == run_span.context.span_id


def test_the_detail_payload_is_never_exported():
    """`detail` can hold prompt and observation text; a trace backend is another boundary."""
    sink = _in_memory_exporter()
    exporter = OTLP_Tracing_Exporter("http://collector:4318", span_exporter=sink)

    exporter.export(_trace(), org_id=ORG, user_id=USER)

    for span in sink.get_finished_spans():
        rendered = repr(dict(span.attributes))
        assert "SECRET PROMPT TEXT" not in rendered
        assert "prompt" not in rendered


def test_a_run_without_a_user_omits_the_user_attribute():
    sink = _in_memory_exporter()
    exporter = OTLP_Tracing_Exporter("http://collector:4318", span_exporter=sink)

    exporter.export(_trace(), org_id=ORG, user_id=None)

    run_span = next(
        span for span in sink.get_finished_spans() if span.name == "agent.run"
    )
    assert "agentforge.user_id" not in run_span.attributes


def test_an_empty_trace_still_produces_a_run_span():
    """A run with no steps is a fact worth exporting; it just has no children."""
    sink = _in_memory_exporter()
    exporter = OTLP_Tracing_Exporter("http://collector:4318", span_exporter=sink)

    exporter.export(Trace(run_id="run-empty", entries=[]), org_id=ORG, user_id=USER)

    spans = sink.get_finished_spans()
    assert [span.name for span in spans] == ["agent.run"]
    assert spans[0].attributes["agentforge.step_count"] == 0


# --- header parsing ---------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        ("x-api-key=abc", {"x-api-key": "abc"}),
        (" x-api-key = abc , x-scope = team ", {"x-api-key": "abc", "x-scope": "team"}),
        # Malformed pairs are skipped, never raised: a header typo must not stop a boot.
        ("broken,x-api-key=abc", {"x-api-key": "abc"}),
        ("=novalue", None),
    ],
)
def test_header_parsing(raw, expected):
    assert OTLP_Tracing_Exporter._parse_headers(raw) == expected
