"""Property-based test for Disabled-never-registered and the availability mirror (Property 2)."""

from __future__ import annotations

from functools import lru_cache

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.config.container import (
    build_app_context,
    build_github_connector,
    build_gmail_connector,
    build_google_drive_connector,
    build_slack_connector,
    build_tool_registry,
)
from agentforge.config.settings import Settings
from agentforge.integrations import INTEGRATION_NAMES
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tools.rag_tool import RAG_TOOL_NAME
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8

_CONNECTOR_BUILDERS = {
    "slack": build_slack_connector,
    "gmail": build_gmail_connector,
    "google_drive": build_google_drive_connector,
    "github": build_github_connector,
}


def _credential_attr(name: str) -> str:
    return "slack_bot_token" if name == "slack" else f"{name}_token"


@lru_cache(maxsize=1)
def _app_context():
    """Build one keyless AppContext reused across examples (deterministic, no network)."""
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )  # type: ignore[call-arg]
    return build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )


def _settings(config: dict) -> Settings:
    base = {
        "profile": "local",
        "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "embedding_dimension": _DIM,
    }
    return Settings(**{**base, **config})  # type: ignore[arg-type]


# Feature: agentforge-integrations, Property 2: Disabled integrations are never registered,
# never listed, and hold no network path.
@hyp_settings(max_examples=150, deadline=None)
@given(
    creds=st.lists(st.booleans(), min_size=4, max_size=4),
    toggles=st.lists(st.sampled_from([True, False, None]), min_size=4, max_size=4),
)
def test_disabled_never_registered_and_available_mirrors(creds, toggles):
    """Feature: agentforge-integrations, Property 2: For any configuration, the Tool_Registry
    built by the composition root contains exactly the baseline tools (rag_search, and
    web_search when its own search credential is present) unioned with exactly the Enabled
    integrations; every Disabled integration is absent from both the registry and
    list_specs(), its selected Connector reports available == False, and each Integration_Tool's
    available equals its connector's available (the mirror).

    Validates: Requirements 2.2, 2.3, 2.5, 3.2, 5.2, 5.5, 10.5, 12.3, 13.2, 14.2, 15.2
    """
    config: dict = {}
    for name, has_cred, toggle in zip(INTEGRATION_NAMES, creds, toggles):
        if has_cred:
            config[_credential_attr(name)] = f"SEKRET-{name}"
        if toggle is not None:
            config[f"{name}_enabled"] = toggle

    settings = _settings(config)
    registry = build_tool_registry(settings, _app_context())
    listed = {spec.name for spec in registry.list_specs()}

    # The baseline is rag_search only (no search credential is configured here).
    expected = {RAG_TOOL_NAME}

    for name in INTEGRATION_NAMES:
        enabled = settings.integration_enabled(name)
        connector = _CONNECTOR_BUILDERS[name](settings)
        if enabled:
            expected.add(name)
            assert connector.available is True
            tool = registry.resolve(name)
            assert tool is not None
            # The tool's availability mirrors its connector (Req 5.5).
            assert tool.available is connector.available is True
        else:
            # Disabled: absent from the registry and the listing, connector unavailable.
            assert connector.available is False
            assert registry.resolve(name) is None
            assert name not in listed

    assert listed == expected
