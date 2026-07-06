"""Gmail integration — ``Gmail_Connector`` (ABC + Disabled/Keyed/Mock) and ``Gmail_Tool``.

Mirrors the ``Search_Provider`` seam: an abstract ``Gmail_Connector`` contract, a keyless
``Disabled_Gmail_Connector`` (unavailable, no network), a credentialed
``Keyed_Gmail_Connector`` built only when a token is present (deterministic stand-in with a
transport-level timeout), and a ``Mock_Gmail_Connector`` test double (available, no network,
canned data / injected failures, spying on calls).

``Gmail_Tool`` is an ordinary ``Integration_Tool`` routing ``search_messages`` → up to the
configured max result count of references, ``read_message`` → the identified message, and
``send_message`` → exactly one message to ``to`` (single write), per the design's "The four
Integration_Tools" section (Req 1.1, 1.3, 5.1–5.4, 13.x).
"""

from __future__ import annotations

from abc import abstractmethod

from agentforge.integrations.base import Integration_Connector, Integration_Tool

GMAIL_TOOL_NAME = "gmail"


class Gmail_Connector(Integration_Connector):
    """Abstract Gmail transport contract (mirrors ``Search_Provider``)."""

    @abstractmethod
    def search_messages(self, query: str) -> list[dict]:
        """Return message references matching ``query`` (read)."""
        raise NotImplementedError

    @abstractmethod
    def read_message(self, message_id: str) -> dict:
        """Return the message identified by ``message_id`` (retrieval by id)."""
        raise NotImplementedError

    @abstractmethod
    def send_message(self, to: str, subject: str, body: str) -> dict:
        """Send exactly one message to ``to`` (single write)."""
        raise NotImplementedError


class Disabled_Gmail_Connector(Gmail_Connector):
    """Keyless default: unavailable, performs no network call (Req 5.2)."""

    @property
    def available(self) -> bool:
        return False

    def search_messages(self, query: str) -> list[dict]:
        raise RuntimeError("gmail integration is disabled: no credential configured")

    def read_message(self, message_id: str) -> dict:
        raise RuntimeError("gmail integration is disabled: no credential configured")

    def send_message(self, to: str, subject: str, body: str) -> dict:
        raise RuntimeError("gmail integration is disabled: no credential configured")


class Keyed_Gmail_Connector(Gmail_Connector):
    """Credentialed Gmail connector, constructed only when a token is present.

    A deterministic stand-in for the real Gmail API (Req 4.2, 5.3). A real integration
    replaces the operation bodies with actual HTTP calls bounded by ``timeout_seconds``.
    """

    def __init__(self, token: str, *, timeout_seconds: float = 10.0) -> None:
        if not token:
            raise ValueError("Keyed_Gmail_Connector requires a non-empty token")
        self._token = token
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return True

    def search_messages(self, query: str) -> list[dict]:
        return [{"message_id": f"m-{query}-{i}", "snippet": f"match {i}"} for i in range(3)]

    def read_message(self, message_id: str) -> dict:
        return {"message_id": message_id, "subject": "(subject)", "body": "(body)"}

    def send_message(self, to: str, subject: str, body: str) -> dict:
        return {"to": to, "subject": subject, "ok": True}


class Mock_Gmail_Connector(Gmail_Connector):
    """Test double: available, no network, canned data / injected failures, spies on calls."""

    def __init__(
        self,
        *,
        available: bool = True,
        messages: list[dict] | None = None,
        message: dict | None = None,
        send_result: dict | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._available = available
        self._messages = list(messages) if messages is not None else []
        self._message = message
        self._send_result = send_result
        self._raises = raises
        self.calls: list[tuple[str, dict]] = []

    @property
    def available(self) -> bool:
        return self._available

    def search_messages(self, query: str) -> list[dict]:
        self.calls.append(("search_messages", {"query": query}))
        if self._raises is not None:
            raise self._raises
        return list(self._messages)

    def read_message(self, message_id: str) -> dict:
        self.calls.append(("read_message", {"message_id": message_id}))
        if self._raises is not None:
            raise self._raises
        return self._message or {"message_id": message_id}

    def send_message(self, to: str, subject: str, body: str) -> dict:
        self.calls.append(
            ("send_message", {"to": to, "subject": subject, "body": body})
        )
        if self._raises is not None:
            raise self._raises
        return self._send_result or {"to": to, "subject": subject, "ok": True}


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["search_messages", "read_message", "send_message"],
        },
        "query": {"type": "string", "minLength": 1},
        "message_id": {"type": "string", "minLength": 1},
        "to": {"type": "string", "minLength": 1},
        "subject": {"type": "string"},
        "body": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"action": {"const": "search_messages"}}},
            "then": {"required": ["query"]},
        },
        {
            "if": {"properties": {"action": {"const": "read_message"}}},
            "then": {"required": ["message_id"]},
        },
        {
            "if": {"properties": {"action": {"const": "send_message"}}},
            "then": {"required": ["to", "subject", "body"]},
        },
    ],
}


class Gmail_Tool(Integration_Tool):
    """Search, read, or send Gmail messages (Req 13.x)."""

    @property
    def name(self) -> str:
        return GMAIL_TOOL_NAME

    @property
    def description(self) -> str:
        return "Search Gmail messages, read a message by id, or send a message."

    @property
    def input_schema(self) -> dict:
        return _INPUT_SCHEMA

    def _dispatch(self, arguments: dict, connector: Gmail_Connector) -> dict:
        action = arguments["action"]
        if action == "send_message":
            # Exactly one connector write call, no other side effect (Req 6.5, 13.5).
            message = connector.send_message(
                arguments["to"], arguments["subject"], arguments["body"]
            )
            return {"content": f"sent a message to {arguments['to']}", "message": message}
        if action == "read_message":
            message = connector.read_message(arguments["message_id"])
            return {"content": "read 1 message", "message": message}
        # search_messages: up to the configured max result count of references.
        messages = connector.search_messages(arguments["query"])
        return {"content": f"{len(messages)} message(s) found", "messages": messages}
