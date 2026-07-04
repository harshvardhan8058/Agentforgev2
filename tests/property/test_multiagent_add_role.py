"""Property test for the add-a-role interface round-trip (Property 9).

Since the orchestrator graph is built in a later task, the round-trip is exercised at the
registry + declarative-pipeline level (as the design permits): for any set of additional
roles implementing ``Agent_Role_Interface`` with distinct ``role_id``s and deterministic
``act``s, registering them and building a pipeline resolves each pipeline position to the
exact registered role, each role's contribution round-trips onto the Blackboard_State, and
a duplicate ``role_id`` is rejected — with no modification to any routing core.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.multiagent.models import Plan
from agentforge.multiagent.roles.base import (
    Agent_Role_Interface,
    Agent_Role_Registry,
    DuplicateRoleIdError,
)
from agentforge.multiagent.state import Blackboard_State


class _FakeRole(Agent_Role_Interface):
    """A minimal deterministic role used to exercise the add-a-role seam."""

    def __init__(self, role_id: str) -> None:
        self._role_id = role_id

    @property
    def role_id(self) -> str:
        return self._role_id

    @property
    def instructions(self) -> str:
        return f"instructions for {self._role_id}"

    def act(self, state: Blackboard_State) -> Blackboard_State:
        # Deterministic contribution keyed by the role id so it can be attributed.
        state.plan = Plan(steps=[f"contribution:{self._role_id}"])
        return state


# Distinct, non-empty role ids (a set guarantees uniqueness).
_role_id_sets = st.lists(
    st.text(alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")), min_size=1, max_size=8),
    min_size=1,
    max_size=6,
    unique=True,
)


# Feature: agentforge-multi-agent, Property 9: Add-a-role interface round-trip
@hyp_settings(max_examples=100, deadline=None)
@given(role_ids=_role_id_sets)
def test_add_a_role_interface_round_trip(role_ids):
    """Feature: agentforge-multi-agent, Property 9: Add-a-role interface round-trip — for
    any additional role that implements the Agent_Role_Interface with a distinct role_id
    and a deterministic act, registering it and inserting its role_id into the pipeline
    yields a registry+pipeline that resolves the new role in its pipeline position and
    carries its contribution on the Blackboard_State, with no modification to the routing
    core.

    Validates: Requirements 1.4
    """
    registry = Agent_Role_Registry()
    roles = [_FakeRole(rid) for rid in role_ids]
    for role in roles:
        registry.register(role)

    # The declarative pipeline is just the ordered list of role ids (data, not code).
    pipeline = list(role_ids)

    # Every pipeline position resolves to the exact registered role instance.
    for position, role_id in enumerate(pipeline):
        resolved = registry.resolve(role_id)
        assert resolved is roles[position]
        assert resolved.role_id == role_id

        # The role's contribution round-trips onto the Blackboard_State.
        state = Blackboard_State(run_id="r", conversation_id="c", task="t")
        updated = resolved.act(state)
        assert updated.plan == Plan(steps=[f"contribution:{role_id}"])

    # registry.roles() reflects registration order.
    assert [r.role_id for r in registry.roles()] == pipeline

    # A distinct role_id is required: re-registering any id is rejected.
    for role in roles:
        try:
            registry.register(_FakeRole(role.role_id))
            raise AssertionError("expected DuplicateRoleIdError")
        except DuplicateRoleIdError:
            pass
