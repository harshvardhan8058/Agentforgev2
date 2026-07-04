"""Documented end-to-end flow test: readiness + ingest -> answer (Task 14.3).

Asserts the two halves of the documented local verification (Req 14.1, 14.2):

1. ``GET /health/ready`` reports ready when the dependencies are reachable, and
2. the ``POST /documents`` -> ``POST /query`` flow returns a grounded, cited answer,

all **keyless** — the LLM is the ``Fallback_Provider``, embeddings are a deterministic
fake, the vector store is an in-process ``Chroma_Store``, and persistence is the
``InMemoryDocumentStore``. Readiness dependencies are simulated with fakes so the test
needs no real Postgres/Redis and stays in the fast suite. The standalone
``scripts/verify_e2e.py`` check is also exercised directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import agentforge.api.routers.health as health_module
from agentforge.config.container import build_app_context
from agentforge.config.settings import Settings
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


class _OkRedis:
    async def ping(self) -> bool:
        return True


@pytest.fixture
def client(monkeypatch) -> TestClient:
    settings = Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )
    ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    app = create_app(settings)
    app.state.app_context = ctx

    # Simulate reachable dependencies for the readiness probe (no real infra).
    async def _db_up(_engine) -> bool:
        return True

    monkeypatch.setattr(health_module, "check_database", _db_up)
    app.state.db_engine = object()
    app.state.redis = _OkRedis()

    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    return TestClient(app, headers=headers, raise_server_exceptions=False)


def test_readiness_then_ingest_and_answer(client: TestClient):
    # 1. Readiness reports ready (Req 14.1).
    ready = client.get("/health/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    # 2. Ingest a sample document.
    doc = b"AgentForge retrieves relevant chunks and answers with citations."
    ingest = client.post("/documents", files={"file": ("sample.txt", doc, "text/plain")})
    assert ingest.status_code == 201
    document_id = ingest.json()["document_id"]

    # 3. Ask a grounded question -> grounded, cited answer keyless (Req 14.2).
    answer = client.post("/query", json={"query": "What does AgentForge return?"})
    assert answer.status_code == 200
    body = answer.json()
    assert body["grounded"] is True
    assert body["provider"] == "fallback"
    assert len(body["citations"]) >= 1
    assert body["citations"][0]["document_id"] == document_id


def test_verify_e2e_script_runs_keyless():
    # The documented standalone verification returns success with the fake embedder
    # (fully offline, no model download). Loaded by file path so it works regardless
    # of how `scripts/` is placed on the path.
    import importlib.util
    from pathlib import Path

    script_path = Path(__file__).resolve().parents[2] / "scripts" / "verify_e2e.py"
    spec = importlib.util.spec_from_file_location("verify_e2e", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.main(["--fake-embeddings"]) == 0
