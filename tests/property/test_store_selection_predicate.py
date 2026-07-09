"""Property 1 (production-hardening, Task 2.1): store-selection predicate is correct
and profile-independent.

Runs fully keyless (no database is contacted — the ``Pg_*`` engines are created lazily and
never connect at construction). For any generated ``Settings`` — varying ``use_database``,
``profile``, and credential presence — each of the nine gated ``build_*`` functions returns
the DB-backed ``Pg_*`` implementation when ``persist_domain_stores()`` is true and the
in-memory implementation when it is false, driven solely by that selector and never by any
credential.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.config import container as c
from agentforge.config.settings import Settings
from agentforge.conversation.store import (
    InMemory_Conversation_Store,
    PgConversation_Store,
)
from agentforge.enterprise.api_keys import InMemory_API_Key_Store, Pg_API_Key_Store
from agentforge.enterprise.identity import InMemory_Identity_Store, Pg_Identity_Store
from agentforge.integrations.connection import (
    InMemory_Integration_Connection_Store,
    Pg_Integration_Connection_Store,
)
from agentforge.multiagent.store import (
    InMemory_Multi_Agent_Run_Store,
    Pg_Multi_Agent_Run_Store,
)
from agentforge.observability.evaluation.store import (
    InMemory_Evaluation_Store,
    Pg_Evaluation_Store,
)
from agentforge.observability.prompt_registry.store import (
    InMemory_Prompt_Store,
    Pg_Prompt_Store,
)
from agentforge.observability.usage.store import InMemory_Usage_Store, Pg_Usage_Store
from agentforge.tracing.recorder import InMemory_Trace_Recorder, Pg_Trace_Recorder

# (builder, DB-backed class, in-memory class) for each of the nine gated Domain_Stores.
_GATED_BUILDERS = [
    (c.build_conversation_store, PgConversation_Store, InMemory_Conversation_Store),
    (c.build_trace_recorder, Pg_Trace_Recorder, InMemory_Trace_Recorder),
    (c.build_identity_store, Pg_Identity_Store, InMemory_Identity_Store),
    (c.build_api_key_store, Pg_API_Key_Store, InMemory_API_Key_Store),
    (c.build_usage_store, Pg_Usage_Store, InMemory_Usage_Store),
    (c.build_prompt_store, Pg_Prompt_Store, InMemory_Prompt_Store),
    (c.build_evaluation_store, Pg_Evaluation_Store, InMemory_Evaluation_Store),
    (
        c.build_multi_agent_run_store,
        Pg_Multi_Agent_Run_Store,
        InMemory_Multi_Agent_Run_Store,
    ),
    (
        c.build_integration_connection_store,
        Pg_Integration_Connection_Store,
        InMemory_Integration_Connection_Store,
    ),
]

_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
}


def _build_settings(use_database, profile, groq_key, jwt_secret) -> Settings:
    overrides: dict = {
        "use_database": use_database,
        "profile": profile,
    }
    # Credentials are varied to prove selection is independent of their presence.
    if groq_key is not None:
        overrides["groq_api_key"] = groq_key
    if jwt_secret is not None:
        overrides["jwt_secret"] = jwt_secret
    return Settings(**{**_BASE, **overrides})


# Feature: production-hardening, Property 1: store-selection predicate is correct and profile-independent
@hyp_settings(max_examples=150, deadline=None)
@given(
    use_database=st.booleans(),
    profile=st.sampled_from(["local", "production"]),
    groq_key=st.none() | st.text(min_size=1, max_size=24),
    jwt_secret=st.none() | st.text(min_size=1, max_size=24),
)
def test_store_selection_predicate_correct_and_profile_independent(
    use_database, profile, groq_key, jwt_secret
):
    """Feature: production-hardening, Property 1: For all Settings, every gated build_*
    returns a Pg_* store when persist_domain_stores() is true and the in-memory store when
    false — independent of any credential's presence.

    Validates: Requirements 1.1, 1.3, 8.1, 8.2, 10.1
    """
    settings = _build_settings(use_database, profile, groq_key, jwt_secret)
    expected_persistent = settings.persist_domain_stores()
    # The selector equals exactly ``use_database OR profile == production`` and depends on
    # nothing else (credentials are irrelevant).
    assert expected_persistent == (use_database or profile == "production")

    for builder, pg_cls, mem_cls in _GATED_BUILDERS:
        store = builder(settings)
        if expected_persistent:
            assert isinstance(store, pg_cls), f"{builder.__name__} should be DB-backed"
        else:
            assert isinstance(store, mem_cls), f"{builder.__name__} should be in-memory"
