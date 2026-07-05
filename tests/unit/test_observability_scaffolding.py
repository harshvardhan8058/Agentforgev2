"""Structural/smoke tests for the Phase 6 observability package (Task 1.1).

Assert the ``observability`` submodules import cleanly; that the declared seams
(``Tracing_Exporter``, ``Usage_Sink``, ``Usage_Store``, ``Cost_Model``, ``Prompt_Store``,
``Guardrail``, ``Evaluator``, ``Evaluation_Store``) are abstract and cannot be
instantiated; that the ``Token_Count`` total invariant holds; that the new Phase 6
settings default to keyless-safe values (``langsmith_api_key is None`` and
``active_tracing_exporter() == "noop"``); and that ``langsmith_api_key`` is redacted from
``repr`` / ``model_dump`` (Req 9.5, 10.1, 10.2, 2.7).
"""

from __future__ import annotations

import importlib

import pytest
from pydantic import SecretStr

from tests.conftest import apply_base_env

_SUBMODULES = [
    "agentforge.observability",
    "agentforge.observability.models",
    "agentforge.observability.tracing_exporter",
    "agentforge.observability.cost",
    "agentforge.observability.analytics",
    "agentforge.observability.usage",
    "agentforge.observability.usage.base",
    "agentforge.observability.usage.instrumented_provider",
    "agentforge.observability.usage.recorder",
    "agentforge.observability.usage.sink",
    "agentforge.observability.usage.store",
    "agentforge.observability.prompt_registry",
    "agentforge.observability.prompt_registry.base",
    "agentforge.observability.prompt_registry.registry",
    "agentforge.observability.prompt_registry.store",
    "agentforge.observability.guardrails",
    "agentforge.observability.guardrails.base",
    "agentforge.observability.guardrails.defaults",
    "agentforge.observability.evaluation",
    "agentforge.observability.evaluation.base",
    "agentforge.observability.evaluation.framework",
    "agentforge.observability.evaluation.evaluators",
    "agentforge.observability.evaluation.store",
]


@pytest.mark.parametrize("module_name", _SUBMODULES)
def test_submodules_import_cleanly(module_name):
    """Every observability submodule imports without error."""
    assert importlib.import_module(module_name) is not None


def test_seam_interfaces_are_abstract():
    """The declared observability seams are ABCs that cannot be instantiated (Req 9.7)."""
    from agentforge.observability.cost import Cost_Model
    from agentforge.observability.evaluation.base import Evaluation_Store, Evaluator
    from agentforge.observability.guardrails.base import Guardrail
    from agentforge.observability.prompt_registry.base import Prompt_Store
    from agentforge.observability.tracing_exporter import Tracing_Exporter
    from agentforge.observability.usage.base import Usage_Sink, Usage_Store

    for interface in (
        Tracing_Exporter,
        Usage_Sink,
        Usage_Store,
        Cost_Model,
        Prompt_Store,
        Guardrail,
        Evaluator,
        Evaluation_Store,
    ):
        with pytest.raises(TypeError):
            interface()  # type: ignore[abstract]


@pytest.mark.parametrize(
    ("prompt", "completion"),
    [(0, 0), (1, 0), (0, 1), (3, 7), (128, 256)],
)
def test_token_count_total_invariant(prompt, completion):
    """``Token_Count.total`` always equals ``prompt + completion`` (Req 2.7)."""
    from agentforge.observability.models import Token_Count

    tokens = Token_Count(prompt=prompt, completion=completion)
    assert tokens.total == prompt + completion


def test_phase6_settings_default_keyless(monkeypatch):
    """The Phase 6 settings are optional and default to keyless-safe values (Req 10.2)."""
    apply_base_env(monkeypatch)
    for var in (
        "LANGSMITH_API_KEY",
        "TRACING_EXPORT_ENABLED",
        "COST_RATE_TABLE_JSON",
        "GUARDRAIL_BLOCKLIST_JSON",
    ):
        monkeypatch.delenv(var, raising=False)

    from agentforge.config.settings import load_settings

    settings = load_settings()

    assert settings.langsmith_api_key is None
    assert settings.langsmith_project == "agentforge"
    assert settings.tracing_export_enabled is True
    assert settings.cost_default_prompt_per_1k == "0.0"
    assert settings.cost_default_completion_per_1k == "0.0"
    assert settings.cost_rate_table_json is None
    assert settings.guardrail_max_input_chars == 8000
    assert settings.guardrail_blocklist_json is None
    # No Tracing_Credential -> the keyless NoOp exporter is active (Req 1.2, 10.2).
    assert settings.active_tracing_exporter() == "noop"


def test_tracing_credential_activates_langsmith(monkeypatch):
    """A configured Tracing_Credential activates the LangSmith exporter (Req 1.4)."""
    apply_base_env(monkeypatch)
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-secret-value")

    from agentforge.config.settings import load_settings

    settings = load_settings()

    assert isinstance(settings.langsmith_api_key, SecretStr)
    assert settings.active_tracing_exporter() == "langsmith"


def test_tracing_export_toggle_forces_noop(monkeypatch):
    """Even with a credential, disabling export keeps the NoOp exporter (Req 1.2)."""
    apply_base_env(monkeypatch)
    monkeypatch.setenv("LANGSMITH_API_KEY", "ls-secret-value")
    monkeypatch.setenv("TRACING_EXPORT_ENABLED", "false")

    from agentforge.config.settings import load_settings

    settings = load_settings()

    assert settings.active_tracing_exporter() == "noop"


def test_langsmith_api_key_is_redacted(monkeypatch):
    """The Tracing_Credential never appears in ``repr`` or ``model_dump`` (Req 9.5, 10.1)."""
    apply_base_env(monkeypatch)
    secret = "ls-super-secret-value"
    monkeypatch.setenv("LANGSMITH_API_KEY", secret)

    from agentforge.config.settings import load_settings

    settings = load_settings()

    assert secret not in repr(settings)
    assert secret not in str(settings)
    dumped = settings.model_dump()
    assert secret not in str(dumped)
    # The raw value remains retrievable only via explicit unwrapping.
    assert settings.langsmith_api_key.get_secret_value() == secret
