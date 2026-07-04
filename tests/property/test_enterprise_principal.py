"""Property test for principal resolution from any credential (Task 7.3 — Property 8).

Deterministic and keyless: an in-memory ``Identity_Store`` + ``API_Key_Store``, a fast
argon2 hasher, and a ``NoOp_Rate_Limiter`` make every branch decidable in-process. The
strategy alternates between valid Bearer / valid API-key credentials and the full family
of invalid credentials (none, malformed, expired, wrong-secret JWT, unknown/revoked key),
asserting a correct :class:`Principal` in the valid branches and a uniform 401 otherwise.
"""

from __future__ import annotations

import uuid

import pytest
from argon2 import PasswordHasher
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st
from starlette.requests import Request

from agentforge.api import deps
from agentforge.api.errors import AppError
from agentforge.enterprise.api_keys import API_Key_Service, InMemory_API_Key_Store
from agentforge.enterprise.auth import Auth_Service
from agentforge.enterprise.identity import InMemory_Identity_Store
from agentforge.enterprise.rate_limit import NoOp_Rate_Limiter
from agentforge.enterprise.rbac import RBAC_Policy, Role

# One fast hasher shared across examples keeps argon2 cost negligible in the property lane.
_FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
_SECRET = "unit-test-signing-secret-value-0123456789"
_OTHER_SECRET = "a-different-signing-secret-value-9876543210"


def _request(headers: dict[str, str]) -> Request:
    """Build a minimal Starlette Request carrying ``headers`` (keyless, deterministic)."""
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


def _fixture() -> tuple[Auth_Service, API_Key_Service, RBAC_Policy]:
    identity = InMemory_Identity_Store()
    rbac = RBAC_Policy()
    auth = Auth_Service(identity, jwt_secret=_SECRET, password_hasher=_FAST_HASHER)
    api_keys = API_Key_Service(InMemory_API_Key_Store(), rbac, _FAST_HASHER)
    return auth, api_keys, rbac


def _resolve(request: Request, auth, api_keys, rbac):
    return deps.get_current_principal(request, auth, api_keys, rbac, NoOp_Rate_Limiter())


# Feature: agentforge-enterprise, Property 8: Principal resolution from any valid
# credential; 401 for any invalid one.
@hyp_settings(max_examples=100, deadline=None)
@given(
    role=st.sampled_from(list(Role)),
    org_id=st.uuids(),
    user_id=st.uuids(),
    credential=st.sampled_from(["jwt", "api_key"]),
    invalid=st.sampled_from(
        ["none", "malformed_jwt", "expired_jwt", "wrong_secret_jwt", "unknown_key", "revoked_key"]
    ),
)
def test_principal_resolution_valid_and_invalid(role, org_id, user_id, credential, invalid):
    """Feature: agentforge-enterprise, Property 8: Principal resolution from any valid
    credential; 401 for any invalid one — a valid JWT or non-revoked API key resolves to a
    Principal whose kind/org/role match and whose permissions derive from the RBAC policy,
    while every malformed/expired/wrong-secret/unknown/revoked credential raises
    AppError("unauthorized", 401).

    Validates: Requirements 1.4, 1.5, 5.3, 7.1
    """
    auth, api_keys, rbac = _fixture()

    # --- valid branch: a well-formed Principal with RBAC-derived permissions ---------
    if credential == "jwt":
        token = auth.issue(user_id, org_id, role)
        principal = _resolve(_request({"Authorization": f"Bearer {token}"}), auth, api_keys, rbac)
        assert principal.kind == "user"
        assert principal.user_id == user_id
        assert principal.key_id is None
    else:  # api_key
        key, secret = api_keys.create(org_id, role)
        principal = _resolve(_request({"X-API-Key": secret}), auth, api_keys, rbac)
        assert principal.kind == "api_key"
        assert principal.key_id == key.id
        assert principal.user_id is None
    assert principal.org_id == org_id
    assert principal.role == role
    assert principal.permissions == rbac.permissions_for(role)

    # --- invalid branch: uniform 401, never a resolved Principal ---------------------
    if invalid == "none":
        headers: dict[str, str] = {}
    elif invalid == "malformed_jwt":
        headers = {"Authorization": "Bearer not-a-jwt"}
    elif invalid == "expired_jwt":
        expired = Auth_Service(
            InMemory_Identity_Store(),
            jwt_secret=_SECRET,
            jwt_expiry_seconds=-10,  # exp lands in the past -> verify returns None
            password_hasher=_FAST_HASHER,
        )
        headers = {"Authorization": f"Bearer {expired.issue(user_id, org_id, role)}"}
    elif invalid == "wrong_secret_jwt":
        other = Auth_Service(
            InMemory_Identity_Store(), jwt_secret=_OTHER_SECRET, password_hasher=_FAST_HASHER
        )
        headers = {"Authorization": f"Bearer {other.issue(user_id, org_id, role)}"}
    elif invalid == "unknown_key":
        headers = {"X-API-Key": f"af_{uuid.uuid4().hex}"}
    else:  # revoked_key
        key, secret = api_keys.create(org_id, role)
        api_keys.revoke(org_id, key.id)
        headers = {"X-API-Key": secret}

    with pytest.raises(AppError) as excinfo:
        _resolve(_request(headers), auth, api_keys, rbac)
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "unauthorized"
