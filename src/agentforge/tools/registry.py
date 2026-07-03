"""Tool_Registry — holds registered Tools and resolves them by name (skeleton).

The registry rejects duplicate names (``DuplicateToolNameError``), resolves a Tool by
name, and lists the specs of available tools only (Req 2.2, 2.3, 2.4, 3.4). The concrete
behavior is implemented in a later task (see task 2.2); the method bodies are placeholders
raising ``NotImplementedError`` so the contract exists without prescribing the logic yet.
"""

from __future__ import annotations

from agentforge.tools.base import Tool_Interface, Tool_Spec


class DuplicateToolNameError(RuntimeError):
    """Raised when registering a Tool under an already-registered name (Req 2.4)."""


class Tool_Registry:
    """Holds registered Tools and resolves them by name for the orchestrator."""

    def register(self, tool: Tool_Interface) -> None:
        """Register ``tool`` under its unique name; reject duplicates (Req 2.2, 2.4)."""
        raise NotImplementedError

    def resolve(self, name: str) -> Tool_Interface | None:
        """Return the Tool registered under ``name``, or ``None`` if unknown (Req 3.4)."""
        raise NotImplementedError

    def list_specs(self) -> list[Tool_Spec]:
        """Return the specs of each AVAILABLE registered tool (Req 2.3, 3.1)."""
        raise NotImplementedError
