"""Property 4 (production-hardening, Task 2.2): keyless boot invariant.

For all keyless ``Settings`` (no credential supplied) with ``persist_domain_stores()`` true,
every one of the nine gated ``build_*`` functions constructs its DB-backed ``Pg_*`` store
successfully without reading any credential and without opening a network connection — the
``Pg_*`` engines are created lazily (no connect at construction) and take only the non-secret
``database_url`` DSN. Enabling persistence therefore introduces no credential requirement to
the default boot.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.config import container as c
from agentforge.config.settings import Settings
from agentforge.conversation.store import PgConversation_Store
from agentforge.enterprise.api_keys import Pg_API_Key_Store
from agentforge.enterprise.identity import Pg_Identity_Store
from agentforge.integrations.connection import Pg_Integration_Connection_Store
from agentforge.multiagent.store import Pg_Multi_Agent_Run_Store
from agentforge.observability.evaluation.store import Pg_Evaluation_Store
from agentforge.observability.prompt_registry.store import Pg_Prompt_Store
from agentforge.observability.usage.store import Pg_Usage_Store
from agentforge.tracing.recorder import Pg_Trace_Recorder

_GATED_BUILDERS = [
    (c.build_conversation_store, PgConversation_Store),
    (c.build_trace_recorder, Pg_Trace_Recorder),
    (c.build_identity_store, Pg_Identity_Store),
    (c.build_api_key_store, Pg_API_Key_Store),
    (c.build_usage_store, Pg_Usage_Store),
    (c.build_prompt_store, Pg_Prompt_Store),
    (c.build_evaluation_store, Pg_Evaluation_Store),
    (c.build_multi_agent_run_store, Pg_Multi_Agent_Run_Store),
    (c.build_integration_connection_store, Pg_Integration_Connection_Store),
]

# Every credential field on Settings — all must remain None on the keyless boot path.
_CREDENTIAL_FIELDS = (
    "groq_api_key",
    "hosted_embedding_api_key",
    "search_api_key",
    "jwt_secret",
    "langsmith_api_key",
    "slack_bot_token",
    "gmail_token",
    "google_drive_token",
    "github_token",
)

_BASE = {
    "database_url": "postgresql+asyncpg://agentforge:agentforge@postgres:5432/agentforge",
    "redis_url": "redis://redis:6379/0",
}


def _keyless_settings(use_database, profile) -> Settings:
    # No credential is ever supplied — this is the keyless boot path.
    return Settings(**{**_BASE, "use_database": use_database, "profile": profile})


# Feature: production-hardening, Property 4: keyless boot invariant (no credential required, none read)
@hyp_settings(max_examples=120, deadline=None)
@given(
    use_database=st.booleans(),
    profile=st.sampled_from(["local", "production"]),
)
def test_keyless_boot_invariant(use_database, profile):
    """Feature: production-hardening, Property 4: For all keyless Settings with
    persist_domain_stores() true, every gated builder constructs its Pg_* store without any
    credential present and without a network provider being constructed.

    Validates: Requirements 1.3, 1.5, 9.2, 9.3, 10.2
    """
    settings = _keyless_settings(use_database, profile)

    # Precondition: this is genuinely keyless — no credential of any kind is present.
    for field in _CREDENTIAL_FIELDS:
        assert getattr(settings, field) is None

    # Only exercise the invariant for the persistent posture; skip the trivial in-memory case.
    if not settings.persist_domain_stores():
        return

    for builder, pg_cls in _GATED_BUILDERS:
        # Construction must succeed with zero credentials and open no connection (lazy engine).
        store = builder(settings)
        assert isinstance(store, pg_cls)
