"""Tool_Registry — holds registered Tools and resolves them by name.

The registry is the single seam through which the Agent_Orchestrator discovers and
resolves Tools. It registers a Tool under its unique name (rejecting duplicates with
``DuplicateToolNameError`` without overwriting the incumbent), resolves a Tool by name
(returning ``None`` when unknown so the orchestrator can emit a ``tool-not-found``
observation), and lists the specs of the currently **available** tools only so a disabled
tool (e.g. web search without a key) is never offered to the LLM (Req 2.2, 2.3, 2.4, 3.4,
5.3, 5.4).

A new Tool is added by implementing ``Tool_Interface`` and calling ``register`` — the
orchestrator is never modified (Req 2.5).
"""

from __future__ import annotations

from agentforge.tools.base import Tool_Interface, Tool_Spec


class DuplicateToolNameError(RuntimeError):
    """Raised when registering a Tool under an already-registered name (Req 2.4)."""


class Tool_Registry:
    """Holds registered Tools and resolves them by name for the orchestrator."""

    def __init__(self) -> None:
        # Insertion-ordered mapping of tool name -> tool; ``dict`` preserves order so
        # ``list_specs`` reports tools in registration order deterministically.
        self._tools: dict[str, Tool_Interface] = {}

    def register(self, tool: Tool_Interface) -> None:
        """Register ``tool`` under its unique name; reject duplicates (Req 2.2, 2.4).

        Raises:
            DuplicateToolNameError: if a Tool is already registered under ``tool.name``.
                The incumbent is left untouched (no overwrite).
        """
        name = tool.name
        if name in self._tools:
            raise DuplicateToolNameError(
                f"a tool named {name!r} is already registered"
            )
        self._tools[name] = tool

    def resolve(self, name: str) -> Tool_Interface | None:
        """Return the Tool registered under ``name``, or ``None`` if unknown (Req 3.4)."""
        return self._tools.get(name)

    def list_specs(self) -> list[Tool_Spec]:
        """Return the specs of each AVAILABLE registered tool (Req 2.3, 3.1).

        Unavailable tools (``tool.available is False``) are omitted so they are never
        offered to the LLM_Provider as a callable option (Req 5.3, 5.4).
        """
        return [
            Tool_Spec(
                name=tool.name,
                description=tool.description,
                input_schema=tool.input_schema,
            )
            for tool in self._tools.values()
            if tool.available
        ]
