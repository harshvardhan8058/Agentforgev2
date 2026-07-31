"""Property: an Organization can never be left without an owner (v1.1 admin CRUD).

The administrative mutations added to the Identity_Store — role reassignment and member
removal — are the only operations that can reduce an Organization's owner count. This
suite drives *arbitrary sequences* of them against a seeded org and asserts the structural
invariant after every step:

    for every organization that has ever had a member, at least one Membership holds
    Role.OWNER

An organization with no administrator is unrecoverable through the API (``manage_members``
is granted to ``OWNER`` alone), so this is a safety property rather than a convenience.
Refusals surface as ``AppError("last_owner", 400)`` and must leave the store unchanged.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from agentforge.api.errors import AppError
from agentforge.enterprise.identity import InMemory_Identity_Store
from agentforge.enterprise.rbac import Role

ROLES = list(Role)

# One operation is either ("promote"/"demote", member_index, role) or ("remove", index).
_operations = st.lists(
    st.one_of(
        st.tuples(
            st.just("set_role"),
            st.integers(min_value=0, max_value=3),
            st.sampled_from(ROLES),
        ),
        st.tuples(st.just("remove"), st.integers(min_value=0, max_value=3)),
    ),
    min_size=1,
    max_size=12,
)


def _seed(member_count: int) -> tuple[InMemory_Identity_Store, object, list]:
    """Return a store holding one org with an OWNER plus ``member_count`` MEMBERs."""
    store = InMemory_Identity_Store()
    org = store.create_organization("Acme")
    users = []
    for index in range(member_count + 1):
        user = store.create_user(f"user-{index}@example.com", "hash")
        store.add_membership(
            user.id, org.id, Role.OWNER if index == 0 else Role.MEMBER
        )
        users.append(user)
    return store, org, users


def _owner_count(store: InMemory_Identity_Store, org_id) -> int:
    return sum(1 for m in store.list_org_members(org_id) if m.role is Role.OWNER)


@settings(max_examples=150, deadline=None)
@given(member_count=st.integers(min_value=0, max_value=3), operations=_operations)
def test_org_always_retains_an_owner(member_count: int, operations: list) -> None:
    store, org, users = _seed(member_count)

    for operation in operations:
        target = users[operation[1] % len(users)]
        before = {
            (m.user_id, m.role) for m in store.list_org_members(org.id)
        }
        try:
            if operation[0] == "set_role":
                store.update_membership_role(target.id, org.id, operation[2])
            else:
                store.remove_membership(target.id, org.id)
        except AppError as exc:
            # The only permitted refusal, and it must be a no-op.
            assert exc.code == "last_owner"
            assert exc.status_code == 400
            assert {
                (m.user_id, m.role) for m in store.list_org_members(org.id)
            } == before

        assert _owner_count(store, org.id) >= 1


@settings(max_examples=50, deadline=None)
@given(operations=_operations)
def test_removals_never_orphan_team_memberships(operations: list) -> None:
    """No Team_Membership may survive its holder's Membership in the team's org (Req 2.5)."""
    store, org, users = _seed(3)
    team = store.create_team(org.id, "eng")
    for user in users:
        store.add_team_member(team.id, user.id)

    for operation in operations:
        target = users[operation[1] % len(users)]
        try:
            if operation[0] == "set_role":
                store.update_membership_role(target.id, org.id, operation[2])
            else:
                store.remove_membership(target.id, org.id)
        except AppError as exc:
            assert exc.code == "last_owner"

        member_ids = {m.user_id for m in store.list_org_members(org.id)}
        team_member_ids = {m.user_id for m in store.list_team_members(org.id, team.id)}
        assert team_member_ids <= member_ids
