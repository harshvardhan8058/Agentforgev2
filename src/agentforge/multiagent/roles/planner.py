"""Planner_Agent — decomposes the task into an ordered Plan.

The Planner reuses the existing Phase 3 ``Agent_Orchestrator`` (injected via the
constructor) for its reasoning rather than introducing a separate text-generation
implementation (Req 1.2, 11.1, 11.2): ``act`` builds a role-scoped request from the
role instructions plus the task, runs the orchestrator, and maps the final answer into a
:class:`Plan`. Under the keyless ``Fallback_Provider`` the orchestrator's output is a pure
function of that request, so identical input yields an identical Plan (Req 1.5); when the
answer contains no parseable steps, a deterministic step list derived from the task text
is used (Req 4.3).
"""

from __future__ import annotations

import re

from agentforge.agent.orchestrator import Agent_Orchestrator
from agentforge.multiagent.models import Plan
from agentforge.multiagent.roles.base import Agent_Role_Interface
from agentforge.multiagent.state import Blackboard_State

# Strips leading list markers ("1.", "-", "*", "a)") so parsed steps are clean prose.
_LIST_MARKER = re.compile(r"^\s*(?:\d+[.)]|[-*\u2022])\s*")


class Planner_Agent(Agent_Role_Interface):
    """The Agent_Role that produces a Plan decomposing the task into steps (Req 1.3, 4.3)."""

    def __init__(self, orchestrator: Agent_Orchestrator) -> None:
        # The SAME existing single-agent orchestrator is injected and reused (Req 11.1).
        self._orchestrator = orchestrator

    @property
    def role_id(self) -> str:
        return "planner"

    @property
    def instructions(self) -> str:
        return (
            "You are the Planner. Decompose the task into a concise, ordered list of "
            "concrete steps, one step per line, that later agents can research, draft, "
            "and review."
        )

    def act(self, state: Blackboard_State) -> Blackboard_State:
        """Produce the Plan and place it on the Blackboard_State (Req 4.3)."""
        request = f"{self.instructions}\n\nTask:\n{state.task}"
        result = self._orchestrator.run(
            request, conversation_id=state.conversation_id
        )
        steps = _parse_steps(result.final_answer or "")
        if not steps:
            steps = _fallback_steps(state.task)
        state.plan = Plan(steps=steps)
        return state


def _parse_steps(text: str) -> list[str]:
    """Extract ordered steps from the answer text, one per non-empty line."""
    steps: list[str] = []
    for line in text.splitlines():
        cleaned = _LIST_MARKER.sub("", line).strip()
        if cleaned:
            steps.append(cleaned)
    return steps


def _fallback_steps(task: str) -> list[str]:
    """Derive a deterministic step list from the task text (Req 4.3, 1.5)."""
    task = task.strip()
    return [
        f"Research information relevant to: {task}",
        f"Draft a response that addresses: {task}",
        f"Review the draft for accuracy and completeness of: {task}",
    ]
