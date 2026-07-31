"""Unit tests for the Identity_Store administrative surface (v1.1 admin CRUD).

Cover the read/update/remove half of member and team management that the create/add-only
Phase 5 store never had:

* ``list_users_by_ids`` batching (deduplicated, unknown ids skipped);
* ``update_membership_role`` / ``remove_membership`` including the **last-owner**
  invariant — an Organization must always retain at least one ``OWNER``;
* removal of a Membership also removing that User's Team_Memberships **inside that org
  only**, because a Team_Membership may exist only for a User holding a Membership in the
  Team's Organization (Req 2.5);
* the org-scoped team reads/writes (``get_team``, ``list_teams``, ``delete_team``,
  ``list_team_members``, ``remove_team_member``) treating another tenant's Team as absent
  rather than forbidden (Req 4.3, 5.7);
* ``add_team_member`` idempotence: a repeat call preserves the original
  ``created_at`` (parity with the Postgres ``ON CONFLICT DO NOTHING`` path).

Every test runs against :class:`InMemory_Identity_Store`, so the lane stays keyless and
deterministic. ``Pg_Identity_Store`` parity is asserted in
``tests/integration/test_enterprise_identity_integration.py``.
"""

from __future__ import annotations

import uuid

import pytest

from agentforge.api.errors import AppError
from agentforge.enterprise.identity import InMemory_Identity_Store, orphans_owner
from agentforge.enterprise.rbac import Role


def _store() -> InMemory_Identity_Store:
    return InMemory_Identity_Store()


def _org_with_owner(store: InMemory_Identity_Store, email: str = "owner@example.com"):
    org = store.create_organization("Acme")
    owner = store.create_user(email, "hash")
    store.add_membership(owner.id, org.id, Role.OWNER)
    return org, owner


# --- list_users_by_ids -------------------------------------------------------------


def test_list_users_by_ids_dedupes_and_skips_unknown():
    store = _store()
    a = store.create_user("a@example.com", "hash")
    b = store.create_user("b@example.com", "hash")

    found = store.list_users_by_ids([a.id, b.id, a.id, uuid.uuid4()])

    assert {u.id for u in found} == {a.id, b.id}
    assert len(found) == 2


def test_list_users_by_ids_empty_input_is_empty():
    assert _store().list_users_by_ids([]) == []


# --- orphans_owner (the shared pure predicate) ------------------------------------


def test_orphans_owner_is_false_when_another_owner_remains():
    keep, drop = uuid.uuid4(), uuid.uuid4()
    roles = [(keep, Role.OWNER), (drop, Role.OWNER)]
    assert orphans_owner(roles, drop, None) is False
    assert orphans_owner(roles, drop, Role.VIEWER) is False


def test_orphans_owner_is_true_for_the_sole_owner():
    sole, other = uuid.uuid4(), uuid.uuid4()
    roles = [(sole, Role.OWNER), (other, Role.ADMIN)]
    assert orphans_owner(roles, sole, None) is True
    assert orphans_owner(roles, sole, Role.ADMIN) is True
    # Re-asserting OWNER on the sole owner is a no-op, not an orphaning change.
    assert orphans_owner(roles, sole, Role.OWNER) is False


def test_orphans_owner_allows_promoting_a_non_owner():
    owner, member = uuid.uuid4(), uuid.uuid4()
    roles = [(owner, Role.OWNER), (member, Role.MEMBER)]
    assert orphans_owner(roles, member, Role.OWNER) is False
    assert orphans_owner(roles, member, Role.ADMIN) is False


# --- update_membership_role -------------------------------------------------------


def test_update_membership_role_changes_role_and_preserves_created_at():
    store = _store()
    org, _owner = _org_with_owner(store)
    member = store.create_user("m@example.com", "hash")
    original = store.add_membership(member.id, org.id, Role.MEMBER)

    updated = store.update_membership_role(member.id, org.id, Role.ADMIN)

    assert updated is not None
    assert updated.role is Role.ADMIN
    assert updated.created_at == original.created_at
    assert store.get_membership(member.id, org.id).role is Role.ADMIN


def test_update_membership_role_unknown_member_is_none():
    store = _store()
    org, _owner = _org_with_owner(store)
    assert store.update_membership_role(uuid.uuid4(), org.id, Role.ADMIN) is None


def test_update_membership_role_cross_org_is_none():
    """A membership in another org is invisible, not forbidden (Req 4.3, 5.7)."""
    store = _store()
    org_a, _owner_a = _org_with_owner(store, "a@example.com")
    org_b = store.create_organization("Beta")
    outsider = store.create_user("b@example.com", "hash")
    store.add_membership(outsider.id, org_b.id, Role.OWNER)

    assert store.update_membership_role(outsider.id, org_a.id, Role.VIEWER) is None
    # Unchanged in its own org.
    assert store.get_membership(outsider.id, org_b.id).role is Role.OWNER


def test_demoting_the_last_owner_is_refused():
    store = _store()
    org, owner = _org_with_owner(store)

    with pytest.raises(AppError) as excinfo:
        store.update_membership_role(owner.id, org.id, Role.ADMIN)

    assert excinfo.value.status_code == 400
    assert excinfo.value.code == "last_owner"
    assert store.get_membership(owner.id, org.id).role is Role.OWNER


def test_demoting_an_owner_is_allowed_once_another_owner_exists():
    store = _store()
    org, owner = _org_with_owner(store)
    second = store.create_user("second@example.com", "hash")
    store.add_membership(second.id, org.id, Role.OWNER)

    updated = store.update_membership_role(owner.id, org.id, Role.VIEWER)

    assert updated.role is Role.VIEWER
    assert store.get_membership(second.id, org.id).role is Role.OWNER


def test_reassigning_owner_to_owner_is_permitted():
    """A no-op update must not trip the last-owner guard."""
    store = _store()
    org, owner = _org_with_owner(store)
    assert store.update_membership_role(owner.id, org.id, Role.OWNER).role is Role.OWNER


# --- remove_membership ------------------------------------------------------------


def test_remove_membership_removes_only_that_orgs_team_memberships():
    store = _store()
    org_a, _owner_a = _org_with_owner(store, "owner-a@example.com")
    org_b = store.create_organization("Beta")
    other_owner = store.create_user("owner-b@example.com", "hash")
    store.add_membership(other_owner.id, org_b.id, Role.OWNER)

    dual = store.create_user("dual@example.com", "hash")
    store.add_membership(dual.id, org_a.id, Role.MEMBER)
    store.add_membership(dual.id, org_b.id, Role.MEMBER)
    team_a = store.create_team(org_a.id, "eng")
    team_b = store.create_team(org_b.id, "eng")  # same name, different org
    store.add_team_member(team_a.id, dual.id)
    store.add_team_member(team_b.id, dual.id)

    assert store.remove_membership(dual.id, org_a.id) is True

    assert store.get_membership(dual.id, org_a.id) is None
    assert store.list_team_members(org_a.id, team_a.id) == []
    # The other tenant is untouched.
    assert store.get_membership(dual.id, org_b.id) is not None
    assert [m.user_id for m in store.list_team_members(org_b.id, team_b.id)] == [dual.id]


def test_remove_membership_unknown_or_cross_org_is_false():
    store = _store()
    org, _owner = _org_with_owner(store)
    assert store.remove_membership(uuid.uuid4(), org.id) is False
    assert store.remove_membership(_owner_id(store, org), uuid.uuid4()) is False


def _owner_id(store: InMemory_Identity_Store, org) -> uuid.UUID:
    return store.list_org_members(org.id)[0].user_id


def test_removing_the_last_owner_is_refused():
    store = _store()
    org, owner = _org_with_owner(store)
    member = store.create_user("m@example.com", "hash")
    store.add_membership(member.id, org.id, Role.MEMBER)

    with pytest.raises(AppError) as excinfo:
        store.remove_membership(owner.id, org.id)

    assert excinfo.value.code == "last_owner"
    assert store.get_membership(owner.id, org.id) is not None
    # A non-owner is removable.
    assert store.remove_membership(member.id, org.id) is True


def test_list_org_members_is_ordered_oldest_first():
    store = _store()
    org, owner = _org_with_owner(store)
    later = store.create_user("later@example.com", "hash")
    store.add_membership(later.id, org.id, Role.MEMBER)

    ordered = store.list_org_members(org.id)

    assert [m.user_id for m in ordered] == [owner.id, later.id]


# --- teams ------------------------------------------------------------------------


def test_get_team_is_org_scoped():
    store = _store()
    org_a, _ = _org_with_owner(store, "a@example.com")
    org_b = store.create_organization("Beta")
    team_b = store.create_team(org_b.id, "eng")

    assert store.get_team(org_b.id, team_b.id).id == team_b.id
    assert store.get_team(org_a.id, team_b.id) is None
    assert store.get_team(org_a.id, uuid.uuid4()) is None


def test_list_teams_is_org_scoped_and_ordered():
    store = _store()
    org_a, _ = _org_with_owner(store, "a@example.com")
    org_b = store.create_organization("Beta")
    first = store.create_team(org_a.id, "platform")
    second = store.create_team(org_a.id, "research")
    store.create_team(org_b.id, "foreign")

    assert [t.id for t in store.list_teams(org_a.id)] == [first.id, second.id]
    assert [t.name for t in store.list_teams(org_b.id)] == ["foreign"]


def test_delete_team_removes_memberships_and_frees_the_name():
    store = _store()
    org, owner = _org_with_owner(store)
    team = store.create_team(org.id, "eng")
    store.add_team_member(team.id, owner.id)

    assert store.delete_team(org.id, team.id) is True

    assert store.list_teams(org.id) == []
    assert store.list_team_members(org.id, team.id) == []
    # The (org, name) uniqueness slot is released, so the name can be reused.
    assert store.create_team(org.id, "eng").id != team.id


def test_delete_team_cross_org_or_unknown_is_false():
    store = _store()
    org_a, _ = _org_with_owner(store, "a@example.com")
    org_b = store.create_organization("Beta")
    team_b = store.create_team(org_b.id, "eng")

    assert store.delete_team(org_a.id, team_b.id) is False
    assert store.delete_team(org_a.id, uuid.uuid4()) is False
    assert store.get_team(org_b.id, team_b.id) is not None


def test_list_team_members_cross_org_is_empty():
    store = _store()
    org_a, _ = _org_with_owner(store, "a@example.com")
    org_b = store.create_organization("Beta")
    owner_b = store.create_user("b@example.com", "hash")
    store.add_membership(owner_b.id, org_b.id, Role.OWNER)
    team_b = store.create_team(org_b.id, "eng")
    store.add_team_member(team_b.id, owner_b.id)

    assert store.list_team_members(org_a.id, team_b.id) == []
    assert len(store.list_team_members(org_b.id, team_b.id)) == 1


def test_remove_team_member_keeps_the_org_membership():
    store = _store()
    org, owner = _org_with_owner(store)
    team = store.create_team(org.id, "eng")
    store.add_team_member(team.id, owner.id)

    assert store.remove_team_member(org.id, team.id, owner.id) is True

    assert store.list_team_members(org.id, team.id) == []
    assert store.get_membership(owner.id, org.id) is not None
    # Idempotent: a second removal reports "nothing removed" rather than raising.
    assert store.remove_team_member(org.id, team.id, owner.id) is False


def test_remove_team_member_cross_org_is_false():
    store = _store()
    org_a, _ = _org_with_owner(store, "a@example.com")
    org_b = store.create_organization("Beta")
    owner_b = store.create_user("b@example.com", "hash")
    store.add_membership(owner_b.id, org_b.id, Role.OWNER)
    team_b = store.create_team(org_b.id, "eng")
    store.add_team_member(team_b.id, owner_b.id)

    assert store.remove_team_member(org_a.id, team_b.id, owner_b.id) is False
    assert len(store.list_team_members(org_b.id, team_b.id)) == 1


def test_add_team_member_is_idempotent_and_preserves_created_at():
    store = _store()
    org, owner = _org_with_owner(store)
    team = store.create_team(org.id, "eng")

    first = store.add_team_member(team.id, owner.id)
    again = store.add_team_member(team.id, owner.id)

    assert again.created_at == first.created_at
    assert len(store.list_team_members(org.id, team.id)) == 1



# --- the last-owner rule is about the transition, not the post-state ---------------
#
# A first cut refused any change that left no owner behind, which also refused changes
# to an organization that *already* held none — freezing it completely (including
# removing an unrelated member) under an error that misstated the cause, with no API
# path able to recover it. The HTTP surface never creates that state, but a direct
# write, a cascaded ``users`` delete, or a seed/import can.


def _ownerless_org(store: InMemory_Identity_Store):
    """Return ``(org, admin, member)`` for an organization holding no OWNER."""
    org = store.create_organization("Ownerless")
    admin = store.create_user("admin@example.com", "hash")
    member = store.create_user("member@example.com", "hash")
    store.add_membership(admin.id, org.id, Role.ADMIN)
    store.add_membership(member.id, org.id, Role.MEMBER)
    return org, admin, member


def test_orphans_owner_is_false_when_the_org_already_has_no_owner():
    admin, member = uuid.uuid4(), uuid.uuid4()
    roles = [(admin, Role.ADMIN), (member, Role.MEMBER)]

    assert orphans_owner(roles, member, None) is False
    assert orphans_owner(roles, member, Role.VIEWER) is False
    assert orphans_owner(roles, admin, None) is False


def test_an_ownerless_org_can_still_be_administered():
    store = _store()
    org, admin, member = _ownerless_org(store)

    assert store.remove_membership(member.id, org.id) is True
    assert store.update_membership_role(admin.id, org.id, Role.VIEWER).role is Role.VIEWER
    # And it can be repaired by promoting somebody to owner.
    assert store.update_membership_role(admin.id, org.id, Role.OWNER).role is Role.OWNER


def test_orphans_owner_on_an_empty_roster_is_false():
    """A membership that is not in the roster cannot remove an owner."""
    assert orphans_owner([], uuid.uuid4(), None) is False
