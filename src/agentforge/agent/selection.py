"""Tool-call parsing and the Selection_Strategy seam.

The existing ``LLM_Provider.generate`` returns **text**, not a structured tool call, so
tool selection has two cooperating parts (Req 3.1):

1. **Prompt construction** (:func:`build_selection_prompt`) — serializes the available
   ``Tool_Spec``s (name + description + input schema) alongside the user request and the
   accumulated observations, plus a fixed instruction describing the expected response
   shape: either a final answer or a single tool call encoded as a small JSON object.
2. **Parsing** (:func:`parse_decision`) — extracts the first well-formed decision JSON
   object from the provider's text. When nothing parseable is present, it defaults to a
   final answer using the raw text so a plain-text provider still terminates cleanly.

The ``Selection_Strategy`` seam lets the LLM-driven path and the deterministic keyless
fallback path share the orchestrator's reason node. The
``Deterministic_Fallback_Strategy`` is a pure function of the run state, which is what
makes fallback tool selection reproducible (Req 1.8, 3.5).
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

from agentforge.agent.state import AgentState
from agentforge.tools.base import Tool_Call, Tool_Spec

# The built-in RAG tool's registered name; the fallback strategy prefers it first so the
# keyless agent grounds its answer in the knowledge base (Req 3.5). Kept as a constant to
# avoid importing the concrete RAG_Tool into the selection seam.
RAG_TOOL_NAME = "rag_search"

# The fixed instruction appended to every selection prompt describing the response shape.
_DECISION_INSTRUCTION = (
    "Respond with a single JSON object and nothing else. To call a tool use "
    '{"action": "tool", "tool": "<tool name>", "arguments": { ... }}. '
    'To answer directly use {"action": "final", "answer": "<your answer>"}.'
)


@dataclass(frozen=True)
class Decision:
    """A parsed reasoning decision: either a final answer or a single tool call."""

    is_final: bool
    answer: str | None = None
    tool_call: Tool_Call | None = None

    @classmethod
    def final(cls, answer: str) -> Decision:
        """Build a final-answer decision."""
        return cls(is_final=True, answer=answer, tool_call=None)

    @classmethod
    def tool(cls, tool_call: Tool_Call) -> Decision:
        """Build a tool-call decision."""
        return cls(is_final=False, answer=None, tool_call=tool_call)


def build_selection_prompt(
    user_request: str,
    observations: list,
    specs: list[Tool_Spec],
) -> str:
    """Construct the reasoning prompt presented to the LLM_Provider (Req 3.1).

    Serializes the available tool specs (name/description/input schema), the user
    request, and the accumulated observations, then appends the fixed decision-shape
    instruction.
    """
    tools_block = json.dumps(
        [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in specs
        ],
        indent=2,
        sort_keys=True,
    )
    observations_block = "\n".join(
        f"- ({getattr(obs, 'kind', 'observation')}) {getattr(obs, 'content', obs)}"
        for obs in observations
    )
    return (
        f"User request:\n{user_request}\n\n"
        f"Available tools:\n{tools_block}\n\n"
        f"Observations so far:\n{observations_block or '(none)'}\n\n"
        f"{_DECISION_INSTRUCTION}"
    )


def _iter_json_objects(text: str):
    """Yield candidate parsed JSON objects found in ``text``, left-to-right.

    Scans for balanced ``{...}`` regions (respecting string literals and escapes) and
    attempts to parse each; only ``dict`` results are yielded.
    """
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start : i + 1]
                try:
                    parsed = json.loads(candidate)
                except (ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    yield parsed
                start = -1


def parse_decision(text: str) -> Decision:
    """Extract the first well-formed decision object from ``text`` (Req 3.1).

    A ``{"action": "tool", ...}`` object becomes a tool-call ``Decision``; a
    ``{"action": "final", ...}`` object becomes a final-answer ``Decision``. When no
    parseable decision object is present, the result defaults to a final answer using the
    raw ``text`` as-is, so a plain-text provider still terminates cleanly.
    """
    for obj in _iter_json_objects(text):
        action = obj.get("action")
        if action == "tool":
            tool_name = obj.get("tool") or obj.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name:
                continue
            arguments = obj.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            return Decision.tool(Tool_Call(tool_name=tool_name, arguments=arguments))
        if action == "final":
            answer = obj.get("answer")
            if not isinstance(answer, str):
                answer = text
            return Decision.final(answer)
    # Nothing parseable: treat the raw text as the final answer (Req 3.1).
    return Decision.final(text)


class Selection_Strategy(ABC):
    """Seam that turns the current run state + available tools into a Decision."""

    @abstractmethod
    def select(self, state: AgentState, specs: list[Tool_Spec]) -> Decision:
        """Return the next :class:`Decision` for the reasoning step."""
        raise NotImplementedError


class Deterministic_Fallback_Strategy(Selection_Strategy):
    """Keyless, deterministic tool selection as a pure function of run state (Req 3.5, 1.8).

    - On the first step, if the RAG_Tool is available, select it with
      ``{"query": user_request}`` to ground the answer in the knowledge base.
    - After a RAG_Tool observation has been recorded, select a final answer composed
      deterministically from the recorded observations.
    - If no tools are available (or the RAG_Tool is not offered), select a final answer
      immediately.
    """

    def __init__(self, rag_tool_name: str = RAG_TOOL_NAME) -> None:
        self._rag_tool_name = rag_tool_name

    def select(self, state: AgentState, specs: list[Tool_Spec]) -> Decision:
        rag_available = any(spec.name == self._rag_tool_name for spec in specs)
        rag_observed = any(
            obs.tool_name == self._rag_tool_name for obs in state.observations
        )
        if rag_available and not rag_observed:
            return Decision.tool(
                Tool_Call(
                    tool_name=self._rag_tool_name,
                    arguments={"query": state.user_request},
                )
            )
        return Decision.final(self._compose_answer(state))

    @staticmethod
    def _compose_answer(state: AgentState) -> str:
        """Deterministically compose a final answer from recorded observations."""
        for obs in reversed(state.observations):
            if obs.kind == "tool_result" and obs.content:
                return obs.content
        return state.user_request


class LLM_Selection_Strategy(Selection_Strategy):
    """LLM-driven selection: build a prompt, generate, and parse the decision (Req 3.1)."""

    def __init__(self, llm_provider) -> None:
        self._llm = llm_provider

    def select(self, state: AgentState, specs: list[Tool_Spec]) -> Decision:
        prompt = build_selection_prompt(state.user_request, state.observations, specs)
        result = self._llm.generate(prompt)
        return parse_decision(result.text)
