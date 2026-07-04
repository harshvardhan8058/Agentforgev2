"""Unit tests for InMemory_Identity_Store invariants (Task 4.5).

Cover the ``UNIQUE(user_id, org_id)`` membership rejection, the ``UNIQUE(org_id, name)``
team rejection, and the ``add_team_member`` cross-org rejection raising
``AppError("org_mismatch", 400)`` (Req 2.5, 2.7).
"""

from __future__ import annotations

import pytest

from agentforge.api.errors import AppError
from agentforge.enterprise.identity import InMemory_Identity_Store
from agentforge.enterprise.rbac import Role


def _store() -> InMemory_Identity_Store:
    return InMemory_Identity_Store()


def test_round_trip_create_and_read():
    """Basic create/read round-trip for org, user, membership, team, team member."""
    store = _store()
    org = store.create_organization("Acme")
    user = store.create_user("a@example.com", "hash")
    membership = store.add_membership(user.id, org.id, Role.OWNER)

    assert store.get_organization(org.id) == org
    assert store.get_user(user.id) == user
    assert store.get_user_by_email("a@example.com") == user
    assert store.get_membership(user.id, org.id) == membership
    assert store.list_org_members(org.id) == [membership]
    assert store.list_memberships_for_user(user.id) == [membership]

    team = store.create_team(org.id, "eng")
    tm = store.add_team_member(team.id, user.id)
    assert tm.team_id == team.id and tm.user_id == user.id


def test_duplicate_membership_rejected():
    """A second add_membership for the same (user, org) is rejected (Req 2.7)."""
    store = _store()
    org = store.create_organization("Acme")
    user = store.create_user("a@example.com", "hash")
    store.add_membership(user.id, org.id, Role.MEMBER)

    with pytest.raises(AppError) as excinfo:
        store.add_membership(user.id, org.id, Role.ADMIN)
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "membership_exists"


def test_duplicate_team_name_rejected():
    """A second create_team with the same (org, name) is rejected (UNIQUE(org, name))."""
    store = _store()
    org = store.create_organization("Acme")
    store.create_team(org.id, "eng")

    with pytest.raises(AppError) as excinfo:
        store.create_team(org.id, "eng")
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "team_exists"


def test_duplicate_email_rejected():
    """A second create_user with the same email is rejected (email UNIQUE)."""
    store = _store()
    store.create_user("a@example.com", "hash")
    with pytest.raises(AppError) as excinfo:
        store.create_user("a@example.com", "other-hash")
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "email_exists"


def test_add_team_member_cross_org_raises_org_mismatch():
    """Adding a user with no membership in the team's org raises org_mismatch (Req 2.5)."""
    store = _store()
    org_a = store.create_organization("Acme")
    org_b = store.create_organization("Beta")
    user = store.create_user("a@example.com", "hash")
    # The user is a member of org_b, but the team belongs to org_a.
    store.add_membership(user.id, org_b.id, Role.MEMBER)
    team_a = store.create_team(org_a.id, "eng")

    with pytest.raises(AppError) as excinfo:
        store.add_team_member(team_a.id, user.id)
    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "org_mismatch"
    assert excinfo.value.details == {"required": "membership"}
