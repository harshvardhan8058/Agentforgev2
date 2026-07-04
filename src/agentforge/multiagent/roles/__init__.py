"""Agent_Role implementations and their interface/registry.

The abstract :class:`Agent_Role_Interface`, the :class:`Agent_Role_Registry`, and the
declarative ``DEFAULT_PIPELINE`` live in ``base``; the four built-in roles (Planner,
Researcher, Writer, Critic) each reuse the existing Phase 3 ``Agent_Orchestrator``.
"""

from __future__ import annotations

from agentforge.multiagent.roles.base import (
    DEFAULT_PIPELINE,
    Agent_Role_Interface,
    Agent_Role_Registry,
    DuplicateRoleIdError,
)
from agentforge.multiagent.roles.critic import Critic_Agent
from agentforge.multiagent.roles.planner import Planner_Agent
from agentforge.multiagent.roles.researcher import Researcher_Agent
from agentforge.multiagent.roles.writer import Writer_Agent

__all__ = [
    "DEFAULT_PIPELINE",
    "Agent_Role_Interface",
    "Agent_Role_Registry",
    "DuplicateRoleIdError",
    "Planner_Agent",
    "Researcher_Agent",
    "Writer_Agent",
    "Critic_Agent",
]
