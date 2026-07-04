"""Unit tests for API_Key_Service one-time-return + list metadata shape (Task 5.6).

Assert the plaintext secret is returned exactly once at creation and is absent from the
listing, and that the metadata projection exposes only safe fields — never ``key_hash``
or the secret (Req 5.1, 5.2, 5.4).
"""

from __future__ import annotations

import uuid

from argon2 import PasswordHasher

from agentforge.enterprise.api_keys import (
    API_KEY_PREFIX,
    API_Key_Service,
    InMemory_API_Key_Store,
    to_metadata,
)
from agentforge.enterprise.rbac import RBAC_Policy, Role

_FAST_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)

_METADATA_FIELDS = {"id", "org_id", "role", "key_prefix", "revoked_at", "created_at"}


def _service() -> API_Key_Service:
    return API_Key_Service(InMemory_API_Key_Store(), RBAC_Policy(), _FAST_HASHER)


def test_secret_returned_once_at_creation():
    """create returns a plaintext secret with the expected prefix and no secret field."""
    svc = _service()
    org_id = uuid.uuid4()
    key, secret = svc.create(org_id, Role.ADMIN)

    assert secret.startswith(API_KEY_PREFIX)
    assert key.key_prefix == secret[:8]
    # The persisted metadata object never carries the plaintext secret.
    assert not hasattr(key, "secret")
    assert secret not in key.key_hash


def test_list_returns_metadata_only_shape():
    """list items expose only safe metadata — never key_hash or the secret (Req 5.4)."""
    svc = _service()
    org_id = uuid.uuid4()
    _key, secret = svc.create(org_id, Role.ADMIN)

    listed = svc.list(org_id)
    assert len(listed) == 1

    meta = to_metadata(listed[0])
    assert set(meta.keys()) == _METADATA_FIELDS
    assert "key_hash" not in meta
    assert "secret" not in meta
    # The secret is not recoverable from any metadata value.
    assert all(str(value) != secret for value in meta.values())


def test_list_is_scoped_to_org():
    """list returns only the caller org's keys."""
    svc = _service()
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    svc.create(org_a, Role.MEMBER)
    svc.create(org_a, Role.ADMIN)
    svc.create(org_b, Role.OWNER)

    assert len(svc.list(org_a)) == 2
    assert len(svc.list(org_b)) == 1
