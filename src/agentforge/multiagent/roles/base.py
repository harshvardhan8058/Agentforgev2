"""Agent_Role_Interface, Agent_Role_Registry, and the declarative pipeline.

Every specialized agent implements the abstract :class:`Agent_Role_Interface` — a role
identifier, role instructions, and an ``act`` operation that reads the Blackboard_State
and returns an updated one (Req 1.1) — independently of any concrete role. Roles are held
in an :class:`Agent_Role_Registry` keyed by ``role_id`` (rejecting duplicates), and the
collaboration order is expressed as :data:`DEFAULT_PIPELINE`, a **declarative list of
data** the orchestrator reads when building the graph.

Because the orchestrator depends only on this interface and the pipeline list, a new role
is added by (1) implementing :class:`Agent_Role_Interface`, (2) registering it, and (3)
listing its ``role_id`` in the pipeline — with **no** edit to the orchestrator routing
core (Req 1.4, 13.2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agentforge.multiagent.state import Blackboard_State

# The declarative linear phase order the graph is built from (data, not code). A new role
# is inserted by editing this list (or a settings-driven pipeline), never the core.
DEFAULT_PIPELINE: list[str] = ["planner", "researcher", "writer", "critic"]


class Agent_Role_Interface(ABC):
    """The abstract contract every Agent_Role implements (Req 1.1)."""

    @property
    @abstractmethod
    def role_id(self) -> str:
        """Stable identifier used for routing, tracing, streaming, and persistence."""

    @property
    @abstractmethod
    def instructions(self) -> str:
        """Role-specific instructions injected into the reused Agent_Orchestrator prompt."""

    @abstractmethod
    def act(self, state: Blackboard_State) -> Blackboard_State:
        """Read the Blackboard_State, do this role's work, return an updated copy (Req 1.1)."""


class DuplicateRoleIdError(RuntimeError):
    """Raised when registering a role under an already-registered ``role_id`` (Req 1.4)."""


class Agent_Role_Registry:
    """Holds registered Agent_Roles and resolves them by ``role_id``.

    Mirrors the Phase 3 ``Tool_Registry`` seam: the orchestrator discovers roles through
    the registry and never references a concrete role class, so a new role is added by
    implementing the interface and registering it (Req 1.4, 13.2).
    """

    def __init__(self) -> None:
        # Insertion-ordered mapping so ``roles()`` reports registration order.
        self._roles: dict[str, Agent_Role_Interface] = {}

    def register(self, role: Agent_Role_Interface) -> None:
        """Register ``role`` under its unique ``role_id``; reject duplicates (Req 1.4).

        Raises:
            DuplicateRoleIdError: if a role is already registered under ``role.role_id``.
                The incumbent is left untouched (no overwrite).
        """
        role_id = role.role_id
        if role_id in self._roles:
            raise DuplicateRoleIdError(
                f"a role with id {role_id!r} is already registered"
            )
        self._roles[role_id] = role

    def resolve(self, role_id: str) -> Agent_Role_Interface | None:
        """Return the role registered under ``role_id``, or ``None`` if unknown."""
        return self._roles.get(role_id)

    def roles(self) -> list[Agent_Role_Interface]:
        """Return the registered roles in registration order."""
        return list(self._roles.values())
