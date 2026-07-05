"""Unit tests for Prompt_Registry render error branches and cross-tenant 404 (Task 6.5).

Covers missing-one, missing-several, extra-values-ignored rendering, and a cross-org
``get`` returning 404 — all keyless against the in-memory store.

Requirements: 4.7, 4.8
"""

from __future__ import annotations

import uuid

import pytest

from agentforge.api.errors import AppError
from agentforge.observability.prompt_registry.registry import Prompt_Registry
from agentforge.observability.prompt_registry.store import InMemory_Prompt_Store


def _registry() -> Prompt_Registry:
    return Prompt_Registry(InMemory_Prompt_Store())


def test_render_success_substitutes_all_variables():
    registry = _registry()
    org = uuid.uuid4()
    v = registry.create_version(
        org, "greet", body="Hi {name}, welcome to {place}!",
        variables=["name", "place"],
    )
    rendered = registry.render(v, {"name": "Ada", "place": "AgentForge"})
    assert rendered == "Hi Ada, welcome to AgentForge!"


def test_render_missing_one_variable_raises_400():
    registry = _registry()
    org = uuid.uuid4()
    v = registry.create_version(
        org, "greet", body="Hi {name} {place}", variables=["name", "place"]
    )
    with pytest.raises(AppError) as excinfo:
        registry.render(v, {"name": "Ada"})
    exc = excinfo.value
    assert exc.code == "missing_variable"
    assert exc.status_code == 400
    assert exc.details["missing"] == ["place"]


def test_render_missing_several_variables_lists_all():
    registry = _registry()
    org = uuid.uuid4()
    v = registry.create_version(
        org, "greet", body="{a}{b}{c}", variables=["a", "b", "c"]
    )
    with pytest.raises(AppError) as excinfo:
        registry.render(v, {"b": "x"})
    assert excinfo.value.details["missing"] == ["a", "c"]


def test_render_ignores_extra_values():
    registry = _registry()
    org = uuid.uuid4()
    v = registry.create_version(org, "greet", body="Hi {name}", variables=["name"])
    rendered = registry.render(v, {"name": "Ada", "unused": "ignored"})
    assert rendered == "Hi Ada"


def test_render_no_declared_variables_returns_body_unchanged():
    registry = _registry()
    org = uuid.uuid4()
    v = registry.create_version(org, "static", body="No placeholders here", variables=[])
    assert registry.render(v, {}) == "No placeholders here"


def test_cross_org_get_returns_404():
    store = InMemory_Prompt_Store()
    registry = Prompt_Registry(store)
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    registry.create_version(org_a, "secret", body="owned by A", variables=[])

    # Org B cannot see org A's prompt -> 404 (never 403).
    with pytest.raises(AppError) as excinfo:
        registry.get(org_b, "secret")
    assert excinfo.value.code == "not_found"
    assert excinfo.value.status_code == 404

    # A specific-version cross-org lookup is also 404.
    with pytest.raises(AppError) as excinfo:
        registry.get(org_b, "secret", version=1)
    assert excinfo.value.status_code == 404
