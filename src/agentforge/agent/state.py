"""AgentState, TerminationReason, and Observation — the typed agent run state.

``AgentState`` is the explicit run state carried across every Agent_Step (Req 1.2): it
records the conversation context, the accumulated observations, and the current
iteration count. The graph enforces the key invariants over this state — the count
starts at 0, increments by exactly 1 per completed reason -> act -> observe cycle, never
exceeds the ``iteration_limit`` (Req 1.4, 11.1), and every run terminates with exactly
one ``termination_reason`` (Req 1.7).

These are plain, framework-agnostic dataclasses (consistent with ``models/domain.py``);
they depend on neither FastAPI nor LangGraph so the core stays decoupled.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid runtime import cycles; annotations are strings via __future__.
    from agentforge.conversation.base import Message
    from agentforge.tools.base import Tool_Call


class TerminationReason(str, Enum):
    """The exactly-one reason an Agent_Run ends with (Req 1.7)."""

    FINAL_ANSWER = "final-answer"
    ITERATION_LIMIT_REACHED = "iteration-limit-reached"


@dataclass
class Observation:
    """One recorded outcome fed back into the loop as the agent scratchpad.

    ``kind`` is one of ``"tool_result"``, ``"tool_not_found"``, ``"validation_error"``,
    or ``"tool_execution_error"`` (Req 3.3, 3.4, 11.2, 11.3).
    """

    kind: str
    tool_name: str | None
    content: str


@dataclass
class AgentState:
    """Explicit run state carried across every Agent_Step (Req 1.2)."""

    run_id: str
    conversation_id: str
    # The current user request; never evicted from working context (Req 6.5).
    user_request: str
    # Prior turns loaded from the Conversation_Store.
    conversation_context: list[Message] = field(default_factory=list)
    # Accumulated observations (the agent scratchpad).
    observations: list[Observation] = field(default_factory=list)
    # Non-negative; +1 per completed reason -> act -> observe cycle (Req 1.2).
    iteration_count: int = 0
    # Resolved bound for this run (Req 1.5); defaults to the bounded default.
    iteration_limit: int = 10
    pending_tool_call: Tool_Call | None = None
    final_answer: str | None = None
    termination_reason: TerminationReason | None = None
    # Set when the configured limit was invalid and the default was applied (Req 1.6).
    invalid_limit_flagged: bool = False
