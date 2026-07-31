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
import re
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
    "Respond with a single JSON object and nothing else — no prose before or after it, "
    "and no Markdown code fence. To call a tool use "
    '{"action": "tool", "tool": "<tool name>", "arguments": { ... }}. '
    'To answer directly use {"action": "final", "answer": "<your answer>"}. '
    'Those are the only two allowed values of "action", and the object must contain '
    "exactly one of them: never emit a list of steps or tool calls, never wrap several "
    "objects together, and call at most one tool per response. "
    "Put the complete answer inside the JSON string and escape any newlines as \\n. "
    "Never invent a source, citation, book, author or URL: cite only what appears in "
    "the observations above, and if there is no support for a claim, omit it."
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


def _iter_json_objects(text: str, _depth_budget: int = 4):
    """Yield candidate parsed JSON objects found in ``text``, left-to-right.

    Scans for balanced ``{...}`` regions (respecting string literals and escapes) and
    attempts to parse each; only ``dict`` results are yielded.

    When a balanced region does **not** parse, the scan descends into that region's
    interior and repeats. Models routinely emit a malformed *wrapper* around
    well-formed inner objects — e.g. ``{"action": "order", "steps": [, {...}, {...}]}``,
    whose stray commas make the outer object unparseable while every inner
    ``{"action": "tool", ...}`` is valid. Without descending, such a response yields no
    decision at all and the whole raw JSON envelope leaks out as the "answer".
    ``_depth_budget`` bounds the recursion so deeply nested text cannot blow the stack.
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
                    # ``strict=False`` tolerates literal control characters (real
                    # newlines/tabs) inside string values. Models routinely emit a
                    # multi-line answer inside {"action": "final", "answer": "..."}
                    # without escaping the newlines as \n, which strict JSON rejects.
                    # Without this, such a response fails to parse and the whole raw
                    # JSON envelope leaks out as the "answer".
                    parsed = json.loads(candidate, strict=False)
                except (ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    yield parsed
                elif _depth_budget > 0 and len(candidate) > 2:
                    # Malformed wrapper: look for well-formed objects nested inside it.
                    yield from _iter_json_objects(
                        candidate[1:-1], _depth_budget=_depth_budget - 1
                    )
                start = -1
    if depth > 0 and start != -1 and _depth_budget > 0:
        # The text ends mid-object: a wrapper that was never closed, which happens
        # whenever generation is cut short by a token limit or a provider error. The
        # unterminated wrapper itself can never parse, but objects nested inside it
        # often completed, so descend rather than discarding the whole response.
        yield from _iter_json_objects(
            text[start + 1 :], _depth_budget=_depth_budget - 1
        )


def _decision_from_object(obj: dict) -> Decision | None:
    """Map a parsed JSON object to a Decision, or ``None`` if it is not a decision.

    A ``tool`` action needs a usable tool name; a ``final`` action needs a string answer.
    Objects that carry neither shape are not decisions and are skipped by the caller.
    """
    action = obj.get("action")
    if action == "tool":
        tool_name = obj.get("tool") or obj.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            arguments = obj.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            return Decision.tool(Tool_Call(tool_name=tool_name, arguments=arguments))
        return None
    if action == "final":
        answer = obj.get("answer")
        if isinstance(answer, str):
            return Decision.final(answer)
        return None
    return None


# Recognizes a response that is *shaped* like a decision envelope even when it is not
# valid JSON, so the envelope can be stripped instead of shown to the user verbatim.
_ENVELOPE_SHAPE = re.compile(r'["\']?action["\']?\s*:\s*["\'](?:tool|final|[a-z_]+)["\']')
# Locates the opening quote of an "answer"/"content"/"text" string value.
_ANSWER_KEY = re.compile(r'["\']?(?:answer|content|text|response)["\']?\s*:\s*"')
# A backslash directly followed by a real newline: a half-escaped line break.
_DANGLING_ESCAPE = re.compile(r"\\[ \t]*\r?\n")
# Three or more consecutive newlines, left behind once escapes are resolved.
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
# A Markdown code fence, optionally tagged with a language.
_CODE_FENCE = re.compile(r"^\s*```[a-zA-Z0-9_-]*\s*|\s*```\s*$")


def looks_like_decision_envelope(text: str) -> bool:
    """Return True when ``text`` looks like a raw decision envelope rather than prose.

    Used as the last line of defence: such text must never be surfaced as an answer.
    """
    stripped = _CODE_FENCE.sub("", text).strip()
    return stripped.startswith("{") and bool(_ENVELOPE_SHAPE.search(stripped))


def _unescape_answer(raw: str) -> str:
    """Resolve the escape sequences a model emits inside an answer string.

    Handles the fully escaped form (``\\n``), the half-escaped form (a backslash
    followed by a real line break), and quotes/backslashes, then collapses the runs of
    blank lines those substitutions leave behind.
    """
    # Resolve half-escaped line breaks first so the \\ rule below cannot consume them.
    out = _DANGLING_ESCAPE.sub("\n", raw)
    for token, replacement in (
        ("\\n", "\n"),
        ("\\r", ""),
        ("\\t", "\t"),
        ('\\"', '"'),
        ("\\/", "/"),
        ("\\\\", "\\"),
    ):
        out = out.replace(token, replacement)
    out = _EXCESS_BLANK_LINES.sub("\n\n", out)
    return out.strip()


def _strip_envelope(text: str) -> str:
    """Recover human-readable prose from an unparseable decision envelope.

    Prefers the value of the answer-bearing key. When no such key is present, the
    JSON scaffolding is dropped line-by-line so that whatever prose the model did emit
    survives — an empty result is preferable to showing raw JSON.
    """
    stripped = _CODE_FENCE.sub("", text).strip()
    match = _ANSWER_KEY.search(stripped)
    if match is not None:
        body = stripped[match.end() :]
        # The value runs to the last quote in the envelope; trailing "}" / "," and any
        # whitespace after that quote are structure, not content.
        closing = body.rfind('"')
        if closing != -1 and not body[closing + 1 :].strip(" \t\r\n},]"):
            body = body[:closing]
        recovered = _unescape_answer(body)
        if recovered:
            return recovered
    # No answer key: keep only lines that are not pure JSON structure.
    kept = [
        line
        for line in (
            _unescape_answer(raw_line) for raw_line in stripped.splitlines()
        )
        if line and not _ENVELOPE_SHAPE.search(line) and line.strip("{}[],\"' \t")
    ]
    return _EXCESS_BLANK_LINES.sub("\n\n", "\n".join(kept)).strip()


def parse_decision(text: str) -> Decision:
    """Extract the first well-formed decision object from ``text`` (Req 3.1).

    A ``{"action": "tool", ...}`` object becomes a tool-call ``Decision``; a
    ``{"action": "final", ...}`` object becomes a final-answer ``Decision``. Objects
    carrying any other ``action`` are still envelopes, so they are never surfaced as
    prose: the scan descends into them looking for a usable decision.

    When no decision object can be parsed, a plain-text provider's output is returned
    as-is so it still terminates cleanly — but text that is *shaped* like an envelope is
    stripped down to the prose it contains first. Raw JSON must never reach the user.
    """
    for obj in _iter_json_objects(text):
        decision = _decision_from_object(obj)
        if decision is not None:
            return decision
    # Nothing parseable. Plain prose passes through untouched (Req 3.1); a malformed
    # envelope is reduced to the prose inside it rather than shown verbatim.
    if looks_like_decision_envelope(text):
        return Decision.final(_strip_envelope(text))
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
