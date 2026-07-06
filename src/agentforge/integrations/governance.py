"""Integration governance — the thin security-audit seam for denied integration actions.

Task 8 wires and verifies RBAC / guardrail / rate-limit / tracing over the **reused**
Phase 5/6 seams: an agent run that could drive an Integration_Tool is already gated behind
``require_permission(Permission.RUN_AGENTS)`` (``api/routers/agent.py``), the input
guardrail already short-circuits before any tool runs, the per-principal rate limiter is
already consulted in ``get_current_principal``, and the ``act`` node already records the
tool-call step in the ``Trace`` and contains a raised ``ToolError`` as a bounded
observation. None of those contracts is modified.

The one genuinely new, self-contained seam is recording a **security audit event** when an
under-permissioned Principal is blocked from an integration-driving action (Req 8.2, 10.6,
13.6, 15.6). This module provides that recorder over the standard logging facility, reusing
the existing logging rather than introducing a bespoke mechanism. The event identifies the
acting Principal, the target Integration, and the denied action, and — like every other
surfaced message in this subsystem — carries **no** credential value and **no** internal
stack trace (Req 4.2, 7.6).
"""

from __future__ import annotations

import logging

from agentforge.enterprise.models import Principal

# The dedicated security-audit logger; reuses the standard logging facility so an operator
# routes/records it exactly as any other AgentForge log stream.
audit_logger = logging.getLogger("agentforge.integrations.audit")


def _principal_identity(principal: Principal) -> str:
    """Return a stable, credential-free identifier for the acting Principal.

    Uses the Principal's ``user_id`` or ``key_id`` and its ``org_id`` — never any secret
    (an API-key Principal carries only its opaque key id, never the plaintext secret).
    """
    subject = principal.user_id if principal.user_id is not None else principal.key_id
    return f"{principal.kind}:{subject}"


def record_integration_denial(
    principal: Principal, integration: str, action: str
) -> None:
    """Record a security audit event for a denied integration action (Req 8.2, 10.6).

    Emits a structured warning identifying the acting Principal, its org, the target
    Integration, and the denied action. Contains no credential value and no stack trace
    (Req 4.2, 7.6). Recording is a pure side effect and never raises to the caller.
    """
    try:
        audit_logger.warning(
            "integration action denied",
            extra={
                "event": "integration_action_denied",
                "principal": _principal_identity(principal),
                "org_id": str(principal.org_id),
                "role": getattr(principal.role, "value", str(principal.role)),
                "integration": integration,
                "action": action,
            },
        )
    except Exception:  # pragma: no cover - audit logging must never change an outcome.
        pass
