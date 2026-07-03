"""Tool_Interface and value types (Pluggable Seam: tools).

Every Tool implements the abstract ``Tool_Interface`` — a name, human-readable
description, input schema, availability flag, and an ``invoke`` operation — independently
of any concrete Tool (Req 2.1). The agent core talks only to this contract (and the
``Tool_Registry``), so new tools are added without touching the orchestrator (Req 2.5).

The value types (``Tool_Spec``, ``Tool_Call``, ``Tool_Result``) are plain,
framework-agnostic dataclasses consistent with ``models/domain.py``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Tool_Spec:
    """The public description of a Tool offered to the LLM_Provider (Req 2.3, 3.1)."""

    name: str
    description: str
    input_schema: dict  # JSON-Schema describing the accepted arguments


@dataclass(frozen=True)
class Tool_Call:
    """A request to invoke a named Tool with arguments (Req 3.2)."""

    tool_name: str
    arguments: dict


@dataclass(frozen=True)
class Tool_Result:
    """The output returned by a Tool, fed back into the loop as an observation."""

    tool_name: str
    ok: bool
    content: str
    # Structured payload (e.g. RAG citations, search results).
    data: dict = field(default_factory=dict)


class ToolError(RuntimeError):
    """Raised by a Tool's ``invoke`` on execution failure.

    The orchestrator contains this as a ``tool-execution-error`` observation and
    continues the run rather than crashing the process (Req 11.3).
    """


class Tool_Interface(ABC):
    """Abstract contract every Tool implements (Req 2.1)."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name used for registration and resolution (Req 2.2)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description presented to the LLM_Provider (Req 3.1)."""
        raise NotImplementedError

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """JSON-Schema for arguments; used to validate before invoke (Req 11.2, 11.4)."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Whether this tool is currently usable (e.g. web search with a key).

        Defaults to ``True``; a tool such as the Web_Search_Tool overrides this to mirror
        its provider so a disabled tool is never offered to the LLM (Req 5.3, 5.4).
        """
        return True

    @abstractmethod
    def invoke(self, arguments: dict) -> Tool_Result:
        """Execute the tool.

        Raises:
            ToolError: on execution failure; contained by the orchestrator (Req 11.3).
        """
        raise NotImplementedError
