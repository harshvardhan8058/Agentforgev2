"""Property test for the API-key lifecycle (Task 5.5 — Property 6).

Keyless and in-process: an ``InMemory_API_Key_Store`` plus a low-cost argon2 hasher
exercise the real create/resolve/revoke path across many (org, role) inputs.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from hypothesis import assume, given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.enterprise.api_keys import API_KEY_PREFIX, API_Key_Service, InMemory_API_Key_Store
from agentforge.enterprise.rbac import RBAC_Policy, Role

_ROLES = list(Role)
# A fast argon2 hasher keeps the 100-iteration lifecycle property quick while exercising
# the real argon2id verifier (never a plaintext compare).
_FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)


def _service() -> API_Key_Service:
    return API_Key_Service(InMemory_API_Key_Store(), RBAC_Policy(), _FAST_HASHER)


# Feature: agentforge-enterprise, Property 6: API key lifecycle — create, resolve,
# revoke, cross-org.
@hyp_settings(max_examples=100, deadline=None)
@given(role=st.sampled_from(_ROLES), org_a=st.uuids(), org_b=st.uuids())
def test_api_key_lifecycle(role, org_a, org_b):
    """Feature: agentforge-enterprise, Property 6: API key lifecycle — create, resolve,
    revoke, cross-org — create returns a plaintext secret once such that resolve_key
    returns metadata with org_id = A and permissions = RBAC_Policy.permissions_for(role);
    after revoke, resolve_key returns None; no two keys share an id; the stored key_hash
    does not contain the secret; list_for_org(B) never contains A's keys; and cross-org
    revoke returns None.

    Validates: Requirements 5.1, 5.2, 5.4, 5.5, 5.6, 5.7, 8.5, 10.6
    """
    assume(org_a != org_b)
    svc = _service()
    rbac = RBAC_Policy()

    key, secret = svc.create(org_a, role)
    key2, secret2 = svc.create(org_a, role)

    # (c) no two created keys share an id (and their secrets differ).
    assert key.id != key2.id
    assert secret != secret2

    # (a) the secret resolves to the created key with derived permissions.
    assert secret.startswith(API_KEY_PREFIX)
    resolved = svc.resolve_key(secret)
    assert resolved is not None
    assert resolved.id == key.id
    assert resolved.org_id == org_a
    assert svc.permissions_for(resolved) == rbac.permissions_for(role)

    # (d) the plaintext secret is not embedded in the stored hash.
    assert secret not in key.key_hash

    # (e) B never sees A's keys.
    assert all(k.org_id != org_a for k in svc.list(org_b))

    # (f) a cross-org revoke is a no-op returning None; the key still resolves.
    assert svc.revoke(org_b, key.id) is None
    assert svc.resolve_key(secret) is not None

    # (b) after an in-org revoke, the secret no longer resolves.
    assert svc.revoke(org_a, key.id) is not None
    assert svc.resolve_key(secret) is None
    # The sibling key created in A is unaffected.
    assert svc.resolve_key(secret2) is not None
