"""Property tests for the RBAC_Policy (Tasks 2.3, 2.4 — Properties 2 and 3).

The policy is a pure function of the static ``ROLE_PERMISSIONS`` map, so both properties
are decidable in-process with no external dependency.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.enterprise.rbac import (
    ROLE_PERMISSIONS,
    Permission,
    RBAC_Policy,
    Role,
)

# Strict role ordering viewer ≺ member ≺ admin ≺ owner (Req 3.2).
_ORDERED_ROLES = [Role.VIEWER, Role.MEMBER, Role.ADMIN, Role.OWNER]

_ROLES = list(Role)
_PERMISSIONS = list(Permission)


# Feature: agentforge-enterprise, Property 2: RBAC iff-invariant — is_authorized(r, p)
# is True if and only if p ∈ ROLE_PERMISSIONS[r].
@hyp_settings(max_examples=200, deadline=None)
@given(role=st.sampled_from(_ROLES), permission=st.sampled_from(_PERMISSIONS))
def test_rbac_iff_invariant(role, permission):
    """Feature: agentforge-enterprise, Property 2: RBAC iff-invariant — for any Role r
    and Permission p, RBAC_Policy.is_authorized(r, p) is True iff p ∈ ROLE_PERMISSIONS[r].

    Validates: Requirements 3.3
    """
    policy = RBAC_Policy()
    assert policy.is_authorized(role, permission) is (permission in ROLE_PERMISSIONS[role])


# Feature: agentforge-enterprise, Property 3: Role-permission subset nesting with
# universal read — viewer ⊆ member ⊆ admin ⊆ owner and READ ∈ every role.
@hyp_settings(max_examples=100, deadline=None)
@given(data=st.data())
def test_role_permission_subset_nesting_with_universal_read(data):
    """Feature: agentforge-enterprise, Property 3: Role-permission subset nesting with
    universal read — for any r1 ≺ r2 in viewer ≺ member ≺ admin ≺ owner,
    ROLE_PERMISSIONS[r1] ⊆ ROLE_PERMISSIONS[r2]; and READ ∈ ROLE_PERMISSIONS[r] for every r.

    Validates: Requirements 3.2, 3.5
    """
    policy = RBAC_Policy()
    i = data.draw(st.integers(min_value=0, max_value=len(_ORDERED_ROLES) - 1))
    j = data.draw(st.integers(min_value=i, max_value=len(_ORDERED_ROLES) - 1))
    lower, higher = _ORDERED_ROLES[i], _ORDERED_ROLES[j]

    # Subset nesting: the lower role's permissions are contained in the higher role's.
    assert policy.permissions_for(lower) <= policy.permissions_for(higher)

    # Universal read: every role grants READ.
    for role in _ROLES:
        assert Permission.READ in policy.permissions_for(role)
