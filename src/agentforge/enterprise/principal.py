"""Principal vocabulary and the per-principal rate-limit key helper.

The reusable FastAPI dependencies themselves (``get_current_principal``, the
``require_permission`` factory, and ``get_org_id``) live in :mod:`agentforge.api.deps`
so the transport layer wires them alongside the other request-scoped accessors. This
module owns the two things both the dependency and the rate limiter must agree on: the
:class:`PrincipalKind` vocabulary and the exact shape of the rate-limit key that
guarantees per-principal isolation (Req 6.6).
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a runtime import cycle; only needed for typing.
    from agentforge.enterprise.models import Principal


class PrincipalKind(str, Enum):
    """How a :class:`~agentforge.enterprise.models.Principal` was authenticated."""

    USER = "user"
    API_KEY = "api_key"


def principal_key(principal: Principal) -> str:
    """Return the per-principal rate-limit key for ``principal``.

    ``"user:<user_id>"`` for a User Principal and ``"key:<key_id>"`` for an API-key
    Principal. The key is per-principal so one Principal reaching the limit never
    affects another's count (Req 6.6); the ``Rate_Limiter`` consumes exactly this string.
    """
    if principal.kind == PrincipalKind.USER.value:
        return f"{PrincipalKind.USER.value}:{principal.user_id}"
    return f"{PrincipalKind.API_KEY.value}:{principal.key_id}"
