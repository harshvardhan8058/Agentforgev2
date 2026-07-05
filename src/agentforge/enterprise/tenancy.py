"""Request-scoped tenant context (the ``org_id`` in force for the current call).

Multi-tenancy is threaded explicitly as an ``org_id`` parameter on every store and on the
public service/orchestrator entry points the routers call (design: "org_id as an explicit
parameter on the public entry points"). A single seam — the agent reasoning loop — cannot
carry ``org_id`` on its call surface because tools implement the fixed ``Tool_Interface``
(``invoke(arguments)``) and are shared singletons. For that one bridge the acting
``org_id`` is published here as a context variable by the orchestrator entry points and
read by the ``RAG_Tool`` (and by the trace recording performed deep inside the graph),
so a tool invocation is still tenant-scoped without widening the tool contract.

The context variable is set synchronously at the start of every orchestrator ``run`` /
``stream_run`` (which then executes the graph in the same synchronous call stack), so the
value is always the acting principal's ``org_id`` while tools run and trace entries are
written. :data:`NIL_ORG_ID` is the keyless standalone default used when no principal has
established a tenant (e.g. direct unit tests of a tool in isolation).
"""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

# The all-zero UUID used as the standalone/keyless default tenant when no principal has
# established a request-scoped org (e.g. isolated tool unit tests).
NIL_ORG_ID: UUID = UUID("00000000-0000-0000-0000-000000000000")

_current_org: ContextVar[UUID] = ContextVar("current_org_id", default=NIL_ORG_ID)

# A parallel context var carrying the acting Principal's ``user_id`` (or ``None`` for an
# API-key/unattributed call). Published alongside the org by the orchestrator entry points
# so cross-cutting consumers — e.g. the Phase 6 ``Instrumented_Provider`` — can attribute
# usage to the right user without widening the ``LLM_Provider`` (or tool) contract.
_current_user: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)


def set_current_org(org_id: UUID) -> None:
    """Publish ``org_id`` as the tenant in force for the current synchronous call stack."""
    _current_org.set(org_id)


def current_org() -> UUID:
    """Return the tenant in force for the current call, or :data:`NIL_ORG_ID` if unset."""
    return _current_org.get()


def set_current_user(user_id: UUID | None) -> None:
    """Publish ``user_id`` as the acting user for the current synchronous call stack."""
    _current_user.set(user_id)


def current_user() -> UUID | None:
    """Return the acting user for the current call, or ``None`` if unset."""
    return _current_user.get()
