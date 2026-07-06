"""Property-based test for integration enablement equivalence (Property 1)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.config.settings import Settings
from agentforge.integrations import INTEGRATION_NAMES

_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/agentforge",
    "redis_url": "redis://localhost:6379/0",
}


def _credential_attr(name: str) -> str:
    return "slack_bot_token" if name == "slack" else f"{name}_token"


# Feature: agentforge-integrations, Property 1: Enablement equivalence (total over the
# configuration space).
@hyp_settings(max_examples=200, deadline=None)
@given(
    name=st.sampled_from(INTEGRATION_NAMES),
    credential_present=st.booleans(),
    # The Enable_Setting is true, false, or unset (defaulting to true).
    toggle=st.sampled_from([True, False, None]),
)
def test_enablement_is_credential_and_toggle(name, credential_present, toggle):
    """Feature: agentforge-integrations, Property 1: For any integration and any combination
    of (Credential present or absent) x (Enable_Setting true/false/unset), the integration is
    Enabled iff the Credential is present AND the Enable_Setting is not false, and Disabled
    otherwise — a total function of configuration alone (independent of any persistence).

    Validates: Requirements 3.1, 3.4, 3.6, 3.7, 5.3, 11.5, 12.2, 13.2, 14.2, 15.2
    """
    kwargs = dict(_BASE)
    if credential_present:
        kwargs[_credential_attr(name)] = f"SEKRET-{name}-token"
    if toggle is not None:
        kwargs[f"{name}_enabled"] = toggle

    settings = Settings(**kwargs)  # type: ignore[arg-type]

    expected = credential_present and (toggle is not False)
    assert settings.integration_enabled(name) is expected
