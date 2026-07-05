"""Auth + tenancy applied to the existing routers (Tasks 13.1, 13.2, 14.1).

These drive the real FastAPI app through ``TestClient`` with the keyless in-memory
enterprise context wired on ``app.state`` (in-memory identity + api-key stores, NoOp rate
limiter, dev-generated jwt_secret). They cover:

* **Property 10** — endpoint accepts iff the principal's role grants the required
  permission (403 otherwise), and an unauthenticated request yields 401.
* Unit checks — no-credential 401 on every protected endpoint, viewer -> 403 on a
  ``run_agents`` endpoint, cross-org 404 for a document/conversation, and a revoked API
  key -> 401.
* Wiring — both existing contexts plus the enterprise context are reachable and every
  protected handler carries ``Depends(require_permission(...))``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

from agentforge.config.container import (
    build_agent_context,
    build_app_context,
    build_multi_agent_context,
)
from agentforge.config.settings import Settings
from agentforge.conversation.store import InMemory_Conversation_Store
from agentforge.enterprise.rbac import ROLE_PERMISSIONS, Permission, Role
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.multiagent.store import InMemory_Multi_Agent_Run_Store
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.tracing.recorder import InMemory_Trace_Recorder
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth, issue_principal_headers
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


def _make_settings() -> Settings:
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


def _build_app_and_ctx():
    """Build a keyless app + wire an enterprise context; return ``(app, ctx)``."""
    settings = _make_settings()
    app_ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    agent_ctx = build_agent_context(
        settings,
        app=app_ctx,
        conversation_store=InMemory_Conversation_Store(),
        trace_recorder=InMemory_Trace_Recorder(),
    )
    multi_ctx = build_multi_agent_context(
        settings, agent=agent_ctx, run_store=InMemory_Multi_Agent_Run_Store()
    )
    app = create_app(settings)
    app.state.app_context = app_ctx
    app.state.agent_context = agent_ctx
    app.state.multi_agent_context = multi_ctx
    _headers, _org, ctx = install_enterprise_auth(app, settings)
    app.state.enterprise_context = ctx
    return app, ctx


# A representative set of protected endpoints that can be invoked without a
# pre-existing path resource, each with its required Permission and a request builder.
def _post_documents(client, headers):
    return client.post(
        "/documents",
        files={"file": ("d.txt", b"AgentForge cites its sources.", "text/plain")},
        headers=headers,
    )


def _get_documents(client, headers):
    return client.get("/documents", headers=headers)


def _post_query(client, headers):
    return client.post("/query", json={"query": "hi"}, headers=headers)


def _post_conversation(client, headers):
    return client.post("/conversations", headers=headers)


def _post_agent_run(client, headers):
    return client.post("/agent/run", json={"message": "hi"}, headers=headers)


def _post_multi_agent_run(client, headers):
    return client.post("/multi-agent/runs", json={"task": "hi"}, headers=headers)


_ENDPOINTS = [
    (Permission.INGEST_DOCUMENTS, _post_documents),
    (Permission.READ, _get_documents),
    (Permission.RUN_AGENTS, _post_query),
    (Permission.READ, _post_conversation),
    (Permission.RUN_AGENTS, _post_agent_run),
    (Permission.RUN_AGENTS, _post_multi_agent_run),
]

_APP, _CTX = _build_app_and_ctx()
_CLIENT = TestClient(_APP, raise_server_exceptions=False)


# Feature: agentforge-enterprise, Property 10: Endpoint permission mapping — accepts iff
# role grants required permission.
@hyp_settings(max_examples=100, deadline=None)
@given(role=st.sampled_from(list(Role)), endpoint_index=st.integers(min_value=0, max_value=len(_ENDPOINTS) - 1))
def test_endpoint_accepts_iff_role_grants_permission(role, endpoint_index):
    """Feature: agentforge-enterprise, Property 10: For any protected endpoint E and any
    role r, an authenticated principal with role r in the resource's org is accepted by E
    (not 403) if and only if E's required permission is in ROLE_PERMISSIONS[r]; an
    unauthenticated request yields 401.

    Validates: Requirements 3.4, 7.1, 7.2, 10.5
    """
    required, invoke = _ENDPOINTS[endpoint_index]
    headers, _org_id = issue_principal_headers(
        _CTX, role=role, org_name=f"org-{role.value}-{endpoint_index}",
        email=f"{role.value}-{endpoint_index}@ex.com",
    )
    response = invoke(_CLIENT, headers)

    allowed = required in ROLE_PERMISSIONS[role]
    if allowed:
        assert response.status_code != 403
        assert response.status_code != 401
        assert response.status_code < 500
    else:
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    # An unauthenticated request always yields 401 regardless of role.
    unauth = invoke(_CLIENT, {})
    assert unauth.status_code == 401
    assert unauth.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("endpoint_index", range(len(_ENDPOINTS)))
def test_no_credentials_yields_401_on_every_protected_endpoint(endpoint_index):
    """Every protected endpoint rejects an unauthenticated request with 401 (Req 7.1)."""
    _required, invoke = _ENDPOINTS[endpoint_index]
    response = invoke(_CLIENT, {})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_viewer_role_forbidden_on_run_agents_endpoint():
    """A viewer (read-only) is 403 on a run_agents endpoint (Req 7.2)."""
    headers, _org = issue_principal_headers(
        _CTX, role=Role.VIEWER, org_name="viewer-org", email="viewer@ex.com"
    )
    response = _CLIENT.post("/agent/run", json={"message": "hi"}, headers=headers)
    assert response.status_code == 403
    assert response.json()["error"]["details"]["required"] == "run_agents"


def test_cross_org_document_fetch_returns_404():
    """A document created in org A is a 404 when deleted by a principal in org B (Req 4.3)."""
    headers_a, _org_a = issue_principal_headers(
        _CTX, role=Role.OWNER, org_name="doc-org-a", email="a-docs@ex.com"
    )
    headers_b, _org_b = issue_principal_headers(
        _CTX, role=Role.OWNER, org_name="doc-org-b", email="b-docs@ex.com"
    )
    created = _CLIENT.post(
        "/documents",
        files={"file": ("d.txt", b"tenant A private document.", "text/plain")},
        headers=headers_a,
    )
    assert created.status_code == 201
    doc_id = created.json()["document_id"]

    # Org A sees it; org B gets 404 on delete (indistinguishable from missing).
    assert _CLIENT.delete(f"/documents/{doc_id}", headers=headers_a).status_code in (204,)
    # Re-create for the cross-org check (the previous one was deleted).
    doc_id = _CLIENT.post(
        "/documents",
        files={"file": ("d.txt", b"tenant A private document.", "text/plain")},
        headers=headers_a,
    ).json()["document_id"]
    resp = _CLIENT.delete(f"/documents/{doc_id}", headers=headers_b)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_cross_org_conversation_fetch_returns_404():
    """A conversation created in org A is a 404 when read by a principal in org B (Req 4.3)."""
    headers_a, _org_a = issue_principal_headers(
        _CTX, role=Role.OWNER, org_name="conv-org-a", email="a-conv@ex.com"
    )
    headers_b, _org_b = issue_principal_headers(
        _CTX, role=Role.OWNER, org_name="conv-org-b", email="b-conv@ex.com"
    )
    cid = _CLIENT.post("/conversations", headers=headers_a).json()["conversation_id"]

    assert _CLIENT.get(f"/conversations/{cid}", headers=headers_a).status_code == 200
    resp = _CLIENT.get(f"/conversations/{cid}", headers=headers_b)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_revoked_api_key_is_unauthorized():
    """A revoked API key presented via X-API-Key resolves to no principal -> 401 (Req 5.6)."""
    headers, org_id = issue_principal_headers(
        _CTX, role=Role.ADMIN, org_name="key-org", email="keys@ex.com"
    )
    key, secret = _CTX.api_key_service.create(org_id, Role.MEMBER)

    # The active key authenticates.
    ok = _CLIENT.get("/documents", headers={"X-API-Key": secret})
    assert ok.status_code == 200

    # After revocation the same secret is rejected with 401.
    _CTX.api_key_service.revoke(org_id, key.id)
    revoked = _CLIENT.get("/documents", headers={"X-API-Key": secret})
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "unauthorized"


def test_enterprise_context_and_dependencies_are_wired():
    """Wiring: the enterprise context is reachable and protected handlers declare the dep (Task 14.1)."""
    assert _APP.state.enterprise_context is _CTX
    assert _APP.state.app_context is not None
    assert _APP.state.agent_context is not None
    assert _APP.state.multi_agent_context is not None

    # Every protected route carries the require_permission dependency (Req 7.6): its
    # dependant tree resolves get_current_principal.
    protected_paths = {
        "/documents",
        "/query",
        "/conversations",
        "/agent/run",
        "/multi-agent/runs",
    }
    seen = set()
    for route in _APP.routes:
        path = getattr(route, "path", None)
        if path in protected_paths:
            dep_names = _dependency_names(route)
            assert "get_current_principal" in dep_names, f"{path} missing auth dependency"
            seen.add(path)
    assert seen == protected_paths


def _dependency_names(route) -> set[str]:
    """Collect the callable names in a route's flattened dependency tree."""
    names: set[str] = set()
    dependant = getattr(route, "dependant", None)
    stack = [dependant] if dependant is not None else []
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        if call is not None:
            names.add(getattr(call, "__name__", ""))
        stack.extend(getattr(dep, "dependencies", []))
    return names
