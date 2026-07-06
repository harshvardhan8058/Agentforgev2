"""Property-based test for cross-tenant Integration_Connection isolation (Task 7.4).

Feature: agentforge-integrations, Property 9: Cross-tenant Integration_Connection access
resolves to not_found (404). For any two distinct organizations and any
Integration_Connection owned by the first, a read or mutate of that connection performed
with the second organization's org_id returns no row at the data-access layer and resolves
to AppError("not_found", 404) -- never the other org's data and never a 403.

Validates: Requirements 11.1, 11.2
"""

from __future__ import annotations

from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.api.errors import AppError
from agentforge.integrations.connection import (
    Integration_Connection,
    InMemory_Integration_Connection_Store,
)


def _resolve_or_404(
    store: InMemory_Integration_Connection_Store, org_id: UUID, connection_id: UUID
) -> Integration_Connection:
    """Mirror the router contract: a missing row resolves to 404, never 403 (Req 11.2)."""
    connection = store.get(org_id, connection_id)
    if connection is None:
        raise AppError("not_found", "integration connection not found", 404)
    return connection


_org_pairs = st.lists(st.uuids(), min_size=2, max_size=2, unique=True)
_integration = st.sampled_from(["slack", "gmail", "google_drive", "github"])
_config = st.dictionaries(
    st.text(min_size=1, max_size=12),
    st.text(max_size=20),
    max_size=4,
)


# Feature: agentforge-integrations, Property 9: Cross-tenant Integration_Connection access
# resolves to not_found (404).
@hyp_settings(max_examples=100, deadline=None)
@given(orgs=_org_pairs, integration=_integration, config=_config)
def test_cross_tenant_connection_access_is_not_found(orgs, integration, config):
    org_a, org_b = orgs
    store = InMemory_Integration_Connection_Store()
    created = store.create(org_a, integration, config)

    # Owner (org A) reads its own connection.
    assert _resolve_or_404(store, org_a, created.id).id == created.id
    assert [c.id for c in store.list_for_org(org_a)] == [created.id]

    # Org B: cross-tenant get returns no row and list is empty -- never A's data.
    assert store.get(org_b, created.id) is None
    assert store.list_for_org(org_b) == []

    # And the router-level resolution is AppError("not_found", 404), never 403.
    with pytest.raises(AppError) as excinfo:
        _resolve_or_404(store, org_b, created.id)
    assert excinfo.value.code == "not_found"
    assert excinfo.value.status_code == 404
