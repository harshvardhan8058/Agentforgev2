"""Shared test doubles for the Phase 8 Integration_Layer base behaviors.

These helpers exercise the ``Integration_Tool`` base (``integrations/base.py``) with a
spying connector and a minimal concrete tool subclass — no real credential, no network.
"""

from __future__ import annotations

import time

from agentforge.integrations.base import Integration_Connector, Integration_Tool

PROBE_TOOL_NAME = "probe"


class Spy_Connector(Integration_Connector):
    """A spying connector: records every operation call, with configurable behavior.

    Configurable to be available/unavailable, to return a canned item list, to raise an
    injected failure, or to sleep for an injected latency (to exercise the timeout). It
    performs no network call.
    """

    def __init__(
        self,
        *,
        available: bool = True,
        items: list | None = None,
        raises: Exception | None = None,
        latency: float = 0.0,
    ) -> None:
        self._available = available
        self._items = list(items) if items is not None else []
        self._raises = raises
        self._latency = latency
        self.calls: list[tuple[str, dict]] = []

    @property
    def available(self) -> bool:
        return self._available

    def read(self, **kwargs) -> list:
        self.calls.append(("read", kwargs))
        self._maybe_delay_or_raise()
        return list(self._items)

    def write(self, **kwargs) -> dict:
        self.calls.append(("write", kwargs))
        self._maybe_delay_or_raise()
        return {"written": True, **kwargs}

    def _maybe_delay_or_raise(self) -> None:
        if self._latency:
            time.sleep(self._latency)
        if self._raises is not None:
            raise self._raises


class Probe_Tool(Integration_Tool):
    """A minimal concrete Integration_Tool used to exercise the base behaviors."""

    @property
    def name(self) -> str:
        return PROBE_TOOL_NAME

    @property
    def description(self) -> str:
        return "A probe tool exercising the Integration_Tool base."

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["read", "write"]},
                "text": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def _dispatch(self, arguments: dict, connector) -> dict:
        action = arguments.get("action", "read")
        if action == "write":
            outcome = connector.write(text=arguments.get("text", ""))
            return {"content": "wrote", **outcome}
        items = connector.read(limit=arguments.get("limit"))
        return {"items": items}
