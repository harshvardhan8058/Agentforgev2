"""Integration_Status — org-scoped, RBAC-gated enablement introspection.

A read-only view reporting each integration's name and whether it is Enabled, derived at
request time from ``Settings.integration_enabled`` (Credential presence + Enable_Setting) and
exposing no credential value (Req 9.1, 9.2, 9.5). The RBAC-gated router that surfaces this
service is added in task 6.2; the composition root wires the service in task 4.3.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentforge.config.settings import Settings
from agentforge.integrations import INTEGRATION_NAMES


@dataclass(frozen=True)
class Integration_Status_Entry:
    """One integration's public status: its name and whether it is Enabled.

    Carries no credential value or secret-derived field (Req 9.2, 9.5).
    """

    name: str
    enabled: bool


class Integration_Status_Service:
    """Derives each integration's enablement from ``Settings`` at request time (Req 9.1)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def status(self) -> list[Integration_Status_Entry]:
        """Return one ``{name, enabled}`` entry per integration in canonical order.

        ``enabled`` is derived from ``settings.integration_enabled(name)`` — a pure function
        of the configured Credential presence and Enable_Setting — so no credential value is
        ever exposed (Req 9.1, 9.2, 9.5).
        """
        return [
            Integration_Status_Entry(name, self._settings.integration_enabled(name))
            for name in INTEGRATION_NAMES
        ]
