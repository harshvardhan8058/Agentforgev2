"""Prompt_Registry: versioning, resolution, and rendering over the Prompt_Store seam.

``create_version`` appends ``max+1`` / ``1`` per ``(org_id, name)`` so version numbers
form a contiguous ``1..N`` sequence; ``get`` returns the latest or a specific version and
raises ``AppError("not_found", 404)`` when absent (cross-tenant included); ``render``
substitutes every declared variable and fails closed with
``AppError("missing_variable", 400)`` when any is omitted (Req 4.1-4.9).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timezone
from uuid import UUID

from fastapi import status

from agentforge.api.errors import AppError
from agentforge.observability.models import Prompt_Version
from agentforge.observability.prompt_registry.base import Prompt_Store


def _utcnow() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


def _substitute(body: str, values: dict[str, str], variables: Sequence[str]) -> str:
    """Substitute every declared ``{variable}`` placeholder in ``body`` (Req 4.6).

    Only the template's declared variables are substituted, so stray braces in the body
    are left untouched and never cause a rendering failure.
    """
    rendered = body
    for name in variables:
        rendered = rendered.replace("{" + name + "}", str(values[name]))
    return rendered


class Prompt_Registry:
    """Stores named Prompt_Templates as immutable Prompt_Versions and renders them."""

    def __init__(self, store: Prompt_Store) -> None:
        self._store = store

    def create_version(
        self, org_id: UUID, name: str, body: str, variables: Sequence[str]
    ) -> Prompt_Version:
        """Append a new immutable Prompt_Version numbered ``max+1``/``1`` (Req 4.1, 4.9)."""
        n = self._store.next_version_number(org_id, name)
        version = Prompt_Version(
            id=uuid.uuid4(),
            org_id=org_id,
            template_name=name,
            version=n,
            body=body,
            variables=tuple(variables),
            created_at=_utcnow(),
        )
        return self._store.add_version(version)

    def list_template_names(self, org_id: UUID) -> list[str]:
        """Return every template name for ``org_id`` (ascending); never cross-org (Req 4.8)."""
        return self._store.list_template_names(org_id)

    def list_versions(self, org_id: UUID, name: str) -> list[int]:
        """Return the ascending version numbers for ``(org_id, name)`` (Req 4.5)."""
        return self._store.list_versions(org_id, name)

    def get(
        self, org_id: UUID, name: str, version: int | None = None
    ) -> Prompt_Version:
        """Return the latest or a specific version; raise 404 if absent (Req 4.3, 4.4, 4.8)."""
        found = (
            self._store.get_latest(org_id, name)
            if version is None
            else self._store.get_version(org_id, name, version)
        )
        if found is None:
            raise AppError(
                "not_found",
                "Prompt not found.",
                status.HTTP_404_NOT_FOUND,
            )
        return found

    def render(self, version: Prompt_Version, values: dict[str, str]) -> str:
        """Render ``version`` with ``values``; fail closed on a missing variable (Req 4.6, 4.7)."""
        missing = [name for name in version.variables if name not in values]
        if missing:
            raise AppError(
                "missing_variable",
                "Missing prompt variable(s).",
                status.HTTP_400_BAD_REQUEST,
                {"missing": missing},
            )
        return _substitute(version.body, values, version.variables)
