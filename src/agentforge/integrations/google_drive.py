"""Google Drive integration — ``Google_Drive_Connector`` trio and ``Google_Drive_Tool``.

Mirrors the ``Search_Provider`` seam. The Google Drive contract is **read-only**: it exposes
``list_files`` / ``search_files`` / ``read_file`` and **no** mutate/delete operation, so the
tool structurally cannot modify or delete a file (Req 14.5). Provides a keyless
``Disabled_Google_Drive_Connector`` (unavailable, no network), a credentialed
``Keyed_Google_Drive_Connector`` (deterministic stand-in, transport-level timeout), and a
spying ``Mock_Google_Drive_Connector`` test double.

``Google_Drive_Tool`` routes ``list_files`` / ``search_files`` → up to the configured max
result count of file references and ``read_file`` → content/metadata of ``file_id``, per the
design's "The four Integration_Tools" section (Req 1.1, 1.3, 5.1–5.4, 14.x).
"""

from __future__ import annotations

from abc import abstractmethod

from agentforge.integrations.base import Integration_Connector, Integration_Tool

GOOGLE_DRIVE_TOOL_NAME = "google_drive"


class Google_Drive_Connector(Integration_Connector):
    """Abstract Google Drive transport contract — READ-ONLY (no mutate/delete) (Req 14.5)."""

    @abstractmethod
    def list_files(self) -> list[dict]:
        """Return file references available to the account (read)."""
        raise NotImplementedError

    @abstractmethod
    def search_files(self, query: str) -> list[dict]:
        """Return file references matching ``query`` (read)."""
        raise NotImplementedError

    @abstractmethod
    def read_file(self, file_id: str) -> dict:
        """Return content/metadata of the file identified by ``file_id`` (retrieval by id)."""
        raise NotImplementedError


class Disabled_Google_Drive_Connector(Google_Drive_Connector):
    """Keyless default: unavailable, performs no network call (Req 5.2)."""

    @property
    def available(self) -> bool:
        return False

    def list_files(self) -> list[dict]:
        raise RuntimeError("google_drive integration is disabled: no credential configured")

    def search_files(self, query: str) -> list[dict]:
        raise RuntimeError("google_drive integration is disabled: no credential configured")

    def read_file(self, file_id: str) -> dict:
        raise RuntimeError("google_drive integration is disabled: no credential configured")


class Keyed_Google_Drive_Connector(Google_Drive_Connector):
    """Credentialed, read-only Google Drive connector (deterministic stand-in) (Req 4.2, 5.3)."""

    def __init__(self, token: str, *, timeout_seconds: float = 10.0) -> None:
        if not token:
            raise ValueError("Keyed_Google_Drive_Connector requires a non-empty token")
        self._token = token
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return True

    def list_files(self) -> list[dict]:
        return [{"file_id": f"f-{i}", "name": f"file {i}"} for i in range(3)]

    def search_files(self, query: str) -> list[dict]:
        return [{"file_id": f"f-{query}-{i}", "name": f"match {i}"} for i in range(3)]

    def read_file(self, file_id: str) -> dict:
        return {"file_id": file_id, "name": "(name)", "content": "(content)"}


class Mock_Google_Drive_Connector(Google_Drive_Connector):
    """Test double: available, no network, canned data / injected failures, spies on calls."""

    def __init__(
        self,
        *,
        available: bool = True,
        files: list[dict] | None = None,
        file: dict | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._available = available
        self._files = list(files) if files is not None else []
        self._file = file
        self._raises = raises
        self.calls: list[tuple[str, dict]] = []

    @property
    def available(self) -> bool:
        return self._available

    def list_files(self) -> list[dict]:
        self.calls.append(("list_files", {}))
        if self._raises is not None:
            raise self._raises
        return list(self._files)

    def search_files(self, query: str) -> list[dict]:
        self.calls.append(("search_files", {"query": query}))
        if self._raises is not None:
            raise self._raises
        return list(self._files)

    def read_file(self, file_id: str) -> dict:
        self.calls.append(("read_file", {"file_id": file_id}))
        if self._raises is not None:
            raise self._raises
        return self._file or {"file_id": file_id}


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["list_files", "search_files", "read_file"],
        },
        "query": {"type": "string", "minLength": 1},
        "file_id": {"type": "string", "minLength": 1},
    },
    "required": ["action"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"action": {"const": "search_files"}}},
            "then": {"required": ["query"]},
        },
        {
            "if": {"properties": {"action": {"const": "read_file"}}},
            "then": {"required": ["file_id"]},
        },
    ],
}


class Google_Drive_Tool(Integration_Tool):
    """List, search, or read Google Drive files — read-only (Req 14.x)."""

    @property
    def name(self) -> str:
        return GOOGLE_DRIVE_TOOL_NAME

    @property
    def description(self) -> str:
        return "List Google Drive files, search files by query, or read a file by id."

    @property
    def input_schema(self) -> dict:
        return _INPUT_SCHEMA

    def _dispatch(self, arguments: dict, connector: Google_Drive_Connector) -> dict:
        action = arguments["action"]
        if action == "read_file":
            file = connector.read_file(arguments["file_id"])
            return {"content": "read 1 file", "file": file}
        if action == "search_files":
            files = connector.search_files(arguments["query"])
            return {"content": f"{len(files)} file(s) found", "files": files}
        # list_files: up to the configured max result count of file references.
        files = connector.list_files()
        return {"content": f"{len(files)} file(s)", "files": files}
