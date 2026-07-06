"""GitHub integration — ``GitHub_Connector`` (ABC + Disabled/Keyed/Mock) and ``GitHub_Tool``.

Mirrors the ``Search_Provider`` seam. Provides a keyless ``Disabled_GitHub_Connector``
(unavailable, no network), a credentialed ``Keyed_GitHub_Connector`` (deterministic
stand-in, transport-level timeout), and a spying ``Mock_GitHub_Connector`` test double.

``GitHub_Tool`` routes ``search_code`` / ``search_issues`` → up to the configured max result
count, ``read_repo`` → repo metadata, and ``create_issue`` → exactly one issue (single
write), per the design's "The four Integration_Tools" section
(Req 1.1, 1.3, 5.1–5.4, 15.x).
"""

from __future__ import annotations

from abc import abstractmethod

from agentforge.integrations.base import Integration_Connector, Integration_Tool

GITHUB_TOOL_NAME = "github"


class GitHub_Connector(Integration_Connector):
    """Abstract GitHub transport contract (mirrors ``Search_Provider``)."""

    @abstractmethod
    def search_code(self, query: str) -> list[dict]:
        """Return code search hits matching ``query`` (read)."""
        raise NotImplementedError

    @abstractmethod
    def search_issues(self, query: str) -> list[dict]:
        """Return issue search hits matching ``query`` (read)."""
        raise NotImplementedError

    @abstractmethod
    def read_repo(self, owner: str, repo: str) -> dict:
        """Return metadata for the ``owner/repo`` repository (retrieval by id)."""
        raise NotImplementedError

    @abstractmethod
    def create_issue(self, owner: str, repo: str, title: str, body: str) -> dict:
        """Create exactly one issue in ``owner/repo`` (single write)."""
        raise NotImplementedError


class Disabled_GitHub_Connector(GitHub_Connector):
    """Keyless default: unavailable, performs no network call (Req 5.2)."""

    @property
    def available(self) -> bool:
        return False

    def search_code(self, query: str) -> list[dict]:
        raise RuntimeError("github integration is disabled: no credential configured")

    def search_issues(self, query: str) -> list[dict]:
        raise RuntimeError("github integration is disabled: no credential configured")

    def read_repo(self, owner: str, repo: str) -> dict:
        raise RuntimeError("github integration is disabled: no credential configured")

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> dict:
        raise RuntimeError("github integration is disabled: no credential configured")


class Keyed_GitHub_Connector(GitHub_Connector):
    """Credentialed GitHub connector, constructed only when a token is present.

    A deterministic stand-in for the real GitHub API (Req 4.2, 5.3). A real integration
    replaces the operation bodies with actual HTTP calls bounded by ``timeout_seconds``.
    """

    def __init__(self, token: str, *, timeout_seconds: float = 10.0) -> None:
        if not token:
            raise ValueError("Keyed_GitHub_Connector requires a non-empty token")
        self._token = token
        self._timeout_seconds = timeout_seconds

    @property
    def available(self) -> bool:
        return True

    def search_code(self, query: str) -> list[dict]:
        return [{"path": f"src/file_{i}.py", "repo": "owner/repo"} for i in range(3)]

    def search_issues(self, query: str) -> list[dict]:
        return [{"number": i, "title": f"issue {i}"} for i in range(3)]

    def read_repo(self, owner: str, repo: str) -> dict:
        return {"owner": owner, "repo": repo, "full_name": f"{owner}/{repo}"}

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> dict:
        return {"owner": owner, "repo": repo, "title": title, "number": 1, "ok": True}


class Mock_GitHub_Connector(GitHub_Connector):
    """Test double: available, no network, canned data / injected failures, spies on calls."""

    def __init__(
        self,
        *,
        available: bool = True,
        results: list[dict] | None = None,
        repo: dict | None = None,
        issue_result: dict | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._available = available
        self._results = list(results) if results is not None else []
        self._repo = repo
        self._issue_result = issue_result
        self._raises = raises
        self.calls: list[tuple[str, dict]] = []

    @property
    def available(self) -> bool:
        return self._available

    def search_code(self, query: str) -> list[dict]:
        self.calls.append(("search_code", {"query": query}))
        if self._raises is not None:
            raise self._raises
        return list(self._results)

    def search_issues(self, query: str) -> list[dict]:
        self.calls.append(("search_issues", {"query": query}))
        if self._raises is not None:
            raise self._raises
        return list(self._results)

    def read_repo(self, owner: str, repo: str) -> dict:
        self.calls.append(("read_repo", {"owner": owner, "repo": repo}))
        if self._raises is not None:
            raise self._raises
        return self._repo or {"owner": owner, "repo": repo}

    def create_issue(self, owner: str, repo: str, title: str, body: str) -> dict:
        self.calls.append(
            ("create_issue", {"owner": owner, "repo": repo, "title": title, "body": body})
        )
        if self._raises is not None:
            raise self._raises
        return self._issue_result or {"owner": owner, "repo": repo, "title": title, "number": 1}


_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["search_code", "search_issues", "read_repo", "create_issue"],
        },
        "query": {"type": "string", "minLength": 1},
        "owner": {"type": "string", "minLength": 1},
        "repo": {"type": "string", "minLength": 1},
        "title": {"type": "string", "minLength": 1},
        "body": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": False,
    "allOf": [
        {
            "if": {"properties": {"action": {"const": "search_code"}}},
            "then": {"required": ["query"]},
        },
        {
            "if": {"properties": {"action": {"const": "search_issues"}}},
            "then": {"required": ["query"]},
        },
        {
            "if": {"properties": {"action": {"const": "read_repo"}}},
            "then": {"required": ["owner", "repo"]},
        },
        {
            "if": {"properties": {"action": {"const": "create_issue"}}},
            "then": {"required": ["owner", "repo", "title"]},
        },
    ],
}


class GitHub_Tool(Integration_Tool):
    """Search code/issues, read a repo, or create an issue (Req 15.x)."""

    @property
    def name(self) -> str:
        return GITHUB_TOOL_NAME

    @property
    def description(self) -> str:
        return "Search GitHub code or issues, read repository metadata, or create an issue."

    @property
    def input_schema(self) -> dict:
        return _INPUT_SCHEMA

    def _dispatch(self, arguments: dict, connector: GitHub_Connector) -> dict:
        action = arguments["action"]
        if action == "create_issue":
            # Exactly one connector write call, no other side effect (Req 6.5, 15.5).
            issue = connector.create_issue(
                arguments["owner"],
                arguments["repo"],
                arguments["title"],
                arguments.get("body", ""),
            )
            return {"content": f"created 1 issue in {arguments['owner']}/{arguments['repo']}", "issue": issue}
        if action == "read_repo":
            repo = connector.read_repo(arguments["owner"], arguments["repo"])
            return {"content": "read repo metadata", "repo": repo}
        if action == "search_issues":
            results = connector.search_issues(arguments["query"])
            return {"content": f"{len(results)} issue(s) found", "results": results}
        # search_code
        results = connector.search_code(arguments["query"])
        return {"content": f"{len(results)} code result(s) found", "results": results}
