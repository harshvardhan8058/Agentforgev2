"""Unit tests for the Phase 5 FastAPI dependency chain (Task 7.4).

Cover the concrete branches of ``get_current_principal`` / ``require_permission`` /
``get_org_id``: Bearer-only, X-API-Key-only, both-headers precedence (Bearer first),
missing / malformed Authorization, expired JWT, revoked API key, and the
``require_permission`` 403 with its ``{"required": <perm>}`` details.
"""

from __future__ import annotations

import uuid

import pytest
from argon2 import PasswordHasher
from starlette.requests import Request

from agentforge.api import deps
from agentforge.api.errors import AppError
from agentforge.enterprise.api_keys import API_Key_Service, InMemory_API_Key_Store
from agentforge.enterprise.auth import Auth_Service
from agentforge.enterprise.identity import InMemory_Identity_Store
from agentforge.enterprise.rate_limit import NoOp_Rate_Limiter
from agentforge.enterprise.rbac import Permission, RBAC_Policy, Role

_FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
_SECRET = "unit-test-signing-secret-value-0123456789"


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "headers": raw})


def _fixture():
    identity = InMemory_Identity_Store()
    rbac = RBAC_Policy()
    auth = Auth_Service(identity, jwt_secret=_SECRET, password_hasher=_FAST_HASHER)
    api_keys = API_Key_Service(InMemory_API_Key_Store(), rbac, _FAST_HASHER)
    return auth, api_keys, rbac


def _resolve(headers: dict[str, str]):
    auth, api_keys, rbac = _fixture()
    return deps.get_current_principal(
        _request(headers), auth, api_keys, rbac, NoOp_Rate_Limiter()
    ), (auth, api_keys, rbac)


def test_bearer_only_resolves_user_principal():
    """A valid Bearer token resolves a User Principal with RBAC-derived permissions."""
    auth, api_keys, rbac = _fixture()
    uid, oid = uuid.uuid4(), uuid.uuid4()
    token = auth.issue(uid, oid, Role.MEMBER)
    principal = deps.get_current_principal(
        _request({"Authorization": f"Bearer {token}"}), auth, api_keys, rbac, NoOp_Rate_Limiter()
    )
    assert principal.kind == "user"
    assert principal.user_id == uid
    assert principal.org_id == oid
    assert principal.permissions == rbac.permissions_for(Role.MEMBER)


def test_api_key_only_resolves_api_key_principal():
    """A valid X-API-Key resolves an API-key Principal scoped to its org + role."""
    auth, api_keys, rbac = _fixture()
    oid = uuid.uuid4()
    key, secret = api_keys.create(oid, Role.ADMIN)
    principal = deps.get_current_principal(
        _request({"X-API-Key": secret}), auth, api_keys, rbac, NoOp_Rate_Limiter()
    )
    assert principal.kind == "api_key"
    assert principal.key_id == key.id
    assert principal.org_id == oid
    assert principal.permissions == rbac.permissions_for(Role.ADMIN)


def test_bearer_takes_precedence_over_api_key():
    """When both headers are present, the Bearer token is used first (Req 7.1)."""
    auth, api_keys, rbac = _fixture()
    uid, oid = uuid.uuid4(), uuid.uuid4()
    token = auth.issue(uid, oid, Role.OWNER)
    # A valid API key for a *different* org is also presented; the Bearer wins.
    _key, secret = api_keys.create(uuid.uuid4(), Role.VIEWER)
    principal = deps.get_current_principal(
        _request({"Authorization": f"Bearer {token}", "X-API-Key": secret}),
        auth,
        api_keys,
        rbac,
        NoOp_Rate_Limiter(),
    )
    assert principal.kind == "user"
    assert principal.org_id == oid
    assert principal.role == Role.OWNER


def test_invalid_bearer_does_not_fall_through_to_api_key():
    """A present-but-invalid Bearer raises 401 even if a valid API key is also present."""
    auth, api_keys, rbac = _fixture()
    _key, secret = api_keys.create(uuid.uuid4(), Role.ADMIN)
    with pytest.raises(AppError) as excinfo:
        deps.get_current_principal(
            _request({"Authorization": "Bearer garbage", "X-API-Key": secret}),
            auth,
            api_keys,
            rbac,
            NoOp_Rate_Limiter(),
        )
    assert excinfo.value.status_code == 401


def test_missing_credentials_raises_401():
    """No Authorization and no X-API-Key -> 401 unauthorized."""
    with pytest.raises(AppError) as excinfo:
        _resolve({})
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == "unauthorized"


@pytest.mark.parametrize("header", ["", "Basic abc", "Bearer", "Bearer   "])
def test_malformed_authorization_raises_401(header):
    """A malformed / non-Bearer Authorization header with no API key -> 401."""
    with pytest.raises(AppError) as excinfo:
        _resolve({"Authorization": header})
    assert excinfo.value.status_code == 401


def test_expired_jwt_raises_401():
    """An expired token is rejected (verify returns None) -> 401 (Req 1.5)."""
    identity = InMemory_Identity_Store()
    rbac = RBAC_Policy()
    api_keys = API_Key_Service(InMemory_API_Key_Store(), rbac, _FAST_HASHER)
    expired_auth = Auth_Service(
        identity, jwt_secret=_SECRET, jwt_expiry_seconds=-1, password_hasher=_FAST_HASHER
    )
    token = expired_auth.issue(uuid.uuid4(), uuid.uuid4(), Role.MEMBER)
    with pytest.raises(AppError) as excinfo:
        deps.get_current_principal(
            _request({"Authorization": f"Bearer {token}"}),
            expired_auth,
            api_keys,
            rbac,
            NoOp_Rate_Limiter(),
        )
    assert excinfo.value.status_code == 401


def test_revoked_api_key_raises_401():
    """A revoked API key never resolves to a Principal -> 401 (Req 5.6)."""
    auth, api_keys, rbac = _fixture()
    oid = uuid.uuid4()
    key, secret = api_keys.create(oid, Role.ADMIN)
    api_keys.revoke(oid, key.id)
    with pytest.raises(AppError) as excinfo:
        deps.get_current_principal(
            _request({"X-API-Key": secret}), auth, api_keys, rbac, NoOp_Rate_Limiter()
        )
    assert excinfo.value.status_code == 401


def test_require_permission_allows_when_granted():
    """require_permission returns the Principal when the role grants the permission."""
    auth, api_keys, rbac = _fixture()
    uid, oid = uuid.uuid4(), uuid.uuid4()
    token = auth.issue(uid, oid, Role.MEMBER)
    principal = deps.get_current_principal(
        _request({"Authorization": f"Bearer {token}"}), auth, api_keys, rbac, NoOp_Rate_Limiter()
    )
    dep = deps.require_permission(Permission.RUN_AGENTS)
    assert dep(principal) is principal


def test_require_permission_forbids_with_details():
    """require_permission raises 403 with {'required': <perm>} when not granted (Req 7.2)."""
    auth, api_keys, rbac = _fixture()
    uid, oid = uuid.uuid4(), uuid.uuid4()
    token = auth.issue(uid, oid, Role.VIEWER)
    principal = deps.get_current_principal(
        _request({"Authorization": f"Bearer {token}"}), auth, api_keys, rbac, NoOp_Rate_Limiter()
    )
    dep = deps.require_permission(Permission.MANAGE_MEMBERS)
    with pytest.raises(AppError) as excinfo:
        dep(principal)
    assert excinfo.value.status_code == 403
    assert excinfo.value.code == "forbidden"
    assert excinfo.value.details == {"required": "manage_members"}


def test_get_org_id_returns_principal_org():
    """get_org_id returns the resolved principal's org_id."""
    auth, api_keys, rbac = _fixture()
    uid, oid = uuid.uuid4(), uuid.uuid4()
    token = auth.issue(uid, oid, Role.ADMIN)
    principal = deps.get_current_principal(
        _request({"Authorization": f"Bearer {token}"}), auth, api_keys, rbac, NoOp_Rate_Limiter()
    )
    assert deps.get_org_id(principal) == oid
