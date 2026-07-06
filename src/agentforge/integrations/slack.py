"""Slack integration — ``Slack_Connector`` (ABC + Disabled/Keyed/Mock) and ``Slack_Tool``.

Mirrors the ``Search_Provider`` seam exactly: an abstract ``Slack_Connector`` contract
exposing the operations the ``Slack_Tool`` invokes, a keyless ``Disabled_Slack_Connector``
(unavailable, no network), a credentialed ``Keyed_Slack_Connector`` built only when a token
is present (deterministic stand-in with a transport-level timeout), and a
``Mock_Slack_Connector`` test double (available, no network, canned data / injected
failures, spying on calls).

``Slack_Tool`` is an ordinary ``Integration_Tool`` (a ``Tool_Interface``) discoverable
through the unchanged ``Tool_Registry``. It declares its identity, per-action
``input_schema`` (``additionalProperties: false``), and an action dispatch routing
``read_channel`` → up to ``limit`` recent messages and ``post_message`` → exactly one
message (single write), per the design's "The four Integration_Tools" section
(Req 1.1, 1.3, 5.1–5.4, 12.x).
"""

from __future__ import annotations

from abc import abstractmethod

from agentforge.integrations.base import Integration_Connector, Integration_Tool

SLACK_TOOL_NAME = "slack"


class Slack_Connector(Integration_Connector):
    """Abstract Slack transport contract (mirrors ``Search_Provider``).

    Exposes ``available`` (inherited) plus exactly the two operations ``Slack_Tool``
    invokes. Concrete implementations live below; the network-capable one is constructed
    only in the composition root when a credential is present (Req 5.1, 5.2).
    """

    @abstractmethod
    def read_channel(self, channel: str, limit: int) -> list[dict]:
        """Return up to ``limit`` recent messages from ``channel`` (read)."""
        raise NotImplementedError

    @abstractmethod
    def post_message(self, channel: str, text: str) -> dict:
        """Post exactly one message with ``text`` to ``channel`` (single write)."""
        raise NotImplementedError


class Disabled_Slack_Connector(Slack_Connector):
    """Keyless default: unavailable, performs no network call (Req 5.2).

    Operations raise defensively so an accidental call fails loudly rather than hitting the
    network; the ``Slack_Tool`` guards on ``available`` first, so they are never reached in
    normal operation.
    """

    @property
    def available(self) -> bool:
        return False

    def read_channel(self, channel: str, limit: int) -> list[dict]:
        raise RuntimeError("slack integration is disabled: no credential configured")

    def post_message(self, channel: str, text: str) -> dict:
        raise RuntimeError("slack integration is disabled: no credential configured")


class Keyed_Slack_Connector(Slack_Connector):
    """Credentialed Slack connector, constructed only when a bot token is present.

    A minimal deterministic stand-in for the real Slack API: it reports itself available
    and returns deterministic placeholder data rather than performing a live network call,
    so the composition-root "register only when Enabled" flow is exercisable without a real
    token. A real integration replaces the operation bodies with actual HTTP calls bounded
    by ``timeout_seconds`` while keeping this class behind the ``Slack_Connector`` seam.
    The token is held only here (derived from a ``SecretStr`` in the container) and is never
    surfaced (Req 4.2, 5.3).
    """

    def __init__(self, token: str, *, timeout_seconds: float = 10.0) -> None:
        if not token:
            raise ValueError("Keyed_Slack_Connector requires a non-empty token")
        self._token = token
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return True

    def read_channel(self, channel: str, limit: int) -> list[dict]:
        count = max(int(limit), 0) if limit is not None else 0
        return [
            {"channel": channel, "ts": f"{i}", "text": f"message {i} in {channel}"}
            for i in range(count)
        ]

    def post_message(self, channel: str, text: str) -> dict:
        return {"channel": channel, "text": text, "ok": True}


class Mock_Slack_Connector(Slack_Connector):
    """Test double: available, no network, canned data / injected failures, spies on calls."""

    def __init__(
        self,
        *,
        available: bool = True,
        messages: list[dict] | None = None,
        post_result: dict | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._available = available
        self._messages = list(messages) if messages is not None else []
        self._post_result = post_result
        self._raises = raises
        self.calls: list[tuple[str, dict]] = []

    @property
    def available(self) -> bool:
        return self._available

    def read_channel(self, channel: str, limit: int) -> list[dict]:
        self.calls.append(("read_channel", {"channel": channel, "limit": limit}))
        if self._raises is not None:
            raise self._raises
        return list(self._messages)

    def post_message(self, channel: str, text: str) -> dict:
        self.calls.append(("post_message", {"channel": channel, "text": text}))
        if self._raises is not None:
            raise self._raises
        return self._post_result or {"channel": channel, "text": text, "ok": True}


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["read_channel", "post_message"]},
        "channel": {"type": "string", "minLength": 1},
        "text": {"type": "string", "minLength": 1},
        "limit": {"type": "integer", "minimum": 1},
    },
    # ``channel`` is required by both actions; ``text`` is required only for post_message.
    "required": ["action", "channel"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"action": {"const": "post_message"}}},
            "then": {"required": ["text"]},
        },
    ],
}


class Slack_Tool(Integration_Tool):
    """Read a channel's recent messages or post a message to a channel (Req 12.x)."""

    @property
    def name(self) -> str:
        return SLACK_TOOL_NAME

    @property
    def description(self) -> str:
        return "Read recent messages from a Slack channel or post a message to one."

    @property
    def input_schema(self) -> dict:
        return _INPUT_SCHEMA

    def _dispatch(self, arguments: dict, connector: Slack_Connector) -> dict:
        action = arguments["action"]
        channel = arguments["channel"]
        if action == "post_message":
            # Exactly one connector write call, no other side effect (Req 6.5, 12.5).
            message = connector.post_message(channel, arguments["text"])
            return {"content": f"posted a message to {channel}", "message": message}
        # read_channel: up to ``limit`` recent messages, also bounded by the global cap.
        limit = arguments.get("limit")
        if limit is None:
            limit = self._max_results
        messages = connector.read_channel(channel, int(limit))
        return {"content": f"{len(messages)} message(s) from {channel}", "messages": messages}
