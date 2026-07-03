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

# Imported at runtime (not under TYPE_CHECKING) so the dataclass type hints resolve when
# LangGraph introspects ``AgentState`` as its state schema. Neither module imports
# ``agent.state``, so there is no import cycle.
from agentforge.conversation.base import Message
from agentforge.tools.base import Tool_Call


# The bounded default and inclusive range for the Iteration_Limit (Req 1.5, 1.6).
DEFAULT_ITERATION_LIMIT = 10
MIN_ITERATION_LIMIT = 1
MAX_ITERATION_LIMIT = 100


def resolve_iteration_limit(configured: object | None) -> tuple[int, bool]:
    """Normalize a configured Iteration_Limit into ``(limit, invalid_flag)``.

    The Agent_Orchestrator obtains the Iteration_Limit from the Configuration_Manager as
    a positive integer in ``[1, 100]`` and normalizes it (Req 1.5, 1.6):

    - An integer within ``[1, 100]`` passes through unchanged with ``invalid_flag=False``.
    - ``None`` (absent) resolves to the default ``10`` with ``invalid_flag=False``.
    - Anything else — a non-integer, a boolean, or an integer outside ``[1, 100]`` — is
      rejected: the default ``10`` is applied and ``invalid_flag=True`` records that the
      configured value was invalid.

    Booleans are rejected explicitly because ``bool`` is a subclass of ``int`` in Python
    and ``True``/``False`` are not meaningful iteration limits.
    """
    if configured is None:
        return DEFAULT_ITERATION_LIMIT, False
    if (
        isinstance(configured, int)
        and not isinstance(configured, bool)
        and MIN_ITERATION_LIMIT <= configured <= MAX_ITERATION_LIMIT
    ):
        return configured, False
    # Rejected: apply the bounded default and flag the invalid configuration (Req 1.6).
    return DEFAULT_ITERATION_LIMIT, True


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
    # Structured payload carried from the Tool_Result (e.g. RAG citations), so the
    # final answer can surface citations without re-invoking the tool. Empty for
    # non-tool-result observations.
    data: dict = field(default_factory=dict)


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
    # Transient: the outcome produced by the act node, committed into ``observations`` by
    # the observe node so the two nodes stay single-responsibility (Req 3.3, 11.2, 11.3).
    pending_observation: Observation | None = None
    final_answer: str | None = None
    termination_reason: TerminationReason | None = None
    # Set when the configured limit was invalid and the default was applied (Req 1.6).
    invalid_limit_flagged: bool = False
