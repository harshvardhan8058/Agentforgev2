"""Keyless API integration tests for the Phase 2 endpoints (Task 13.5).

These drive the real FastAPI app through ``TestClient`` end to end —
``POST /documents`` -> ``POST /query`` -> ``GET /documents`` -> ``DELETE`` — using only
keyless, in-memory doubles injected through the composition root:

* ``InMemoryDocumentStore`` (relational persistence + chunk-text source),
* ``Chroma_Store`` (in-process embedded vector store),
* ``Fallback_Provider`` (deterministic, network-free LLM),
* a small deterministic fake embedder (no model download).

No Postgres, Redis, or external credential is required, so the whole module runs in the
fast suite (``pytest -m 'not integration'``) and satisfies Req 2.3, 13.1-13.3.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agentforge.config.container import build_app_context
from agentforge.config.settings import Settings
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.main import create_app
from agentforge.storage.memory_store import InMemoryDocumentStore
from agentforge.vectorstore.chroma_store import Chroma_Store

from tests.enterprise_helpers import install_enterprise_auth
from tests.fakes import DeterministicFakeEmbeddings

_DIM = 8


def _make_settings() -> Settings:
    """A valid local-profile Settings object (no credentials)."""
    return Settings(
        profile="local",
        database_url="postgresql+asyncpg://u:p@localhost:5432/agentforge",
        redis_url="redis://localhost:6379/0",
        embedding_dimension=_DIM,
    )


@pytest.fixture
def client() -> TestClient:
    """A TestClient wired with keyless in-memory doubles (no lifespan/infra)."""
    settings = _make_settings()
    ctx = build_app_context(
        settings,
        embedding_provider=DeterministicFakeEmbeddings(dimension=_DIM),
        vector_store=Chroma_Store(dim=_DIM),
        llm_provider=Fallback_Provider(),
        document_store=InMemoryDocumentStore(),
    )
    app = create_app(settings)
    app.state.app_context = ctx
    # Wire a keyless enterprise context + auth headers; every request authenticates as an
    # owner in a single org, so ingested docs and queries share that tenant.
    headers, _org_id, _ctx = install_enterprise_auth(app, settings)
    # No `with`: skip the real lifespan (migrations / DB / Redis) — the context is
    # already injected above.
    return TestClient(app, headers=headers, raise_server_exceptions=False)


def _ingest(client: TestClient, name: str, data: bytes, content_type: str):
    return client.post(
        "/documents",
        files={"file": (name, data, content_type)},
    )


def test_full_ingest_query_list_delete_flow(client: TestClient):
    # 1. Ingest a text document -> 201 with a chunk count.
    body = b"AgentForge grounds answers in retrieved chunks and cites their sources."
    resp = _ingest(client, "doc.txt", body, "text/plain")
    assert resp.status_code == 201
    payload = resp.json()
    document_id = payload["document_id"]
    assert payload["filename"] == "doc.txt"
    assert payload["status"] == "ingested"
    assert payload["chunk_count"] >= 1

    # 2. Query -> 200 grounded answer with one citation per used chunk.
    resp = client.post("/query", json={"query": "How does AgentForge answer?"})
    assert resp.status_code == 200
    answer = resp.json()
    assert answer["grounded"] is True
    assert answer["provider"] == "fallback"
    assert len(answer["citations"]) >= 1
    assert all(c["document_id"] == document_id for c in answer["citations"])

    # 3. List -> the ingested document is present with its chunk count.
    resp = client.get("/documents")
    assert resp.status_code == 200
    listing = resp.json()
    assert len(listing) == 1
    assert listing[0]["document_id"] == document_id
    assert listing[0]["chunk_count"] == payload["chunk_count"]

    # 4. Delete -> 204, and it disappears from the listing.
    resp = client.delete(f"/documents/{document_id}")
    assert resp.status_code == 204
    assert client.get("/documents").json() == []


def test_query_with_no_documents_is_grounded_false_no_citation(client: TestClient):
    resp = client.post("/query", json={"query": "anything at all"})
    assert resp.status_code == 200
    answer = resp.json()
    assert answer["grounded"] is False
    assert answer["citations"] == []
    # No fabricated source or content (Req 12.5).
    assert "no grounding information" in answer["answer"].lower()


def test_top_k_out_of_range_is_rejected_by_schema(client: TestClient):
    # top_k is bounded [1, 10] by the request schema -> validation error envelope.
    resp = client.post("/query", json={"query": "q", "top_k": 99})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "validation_error"


def test_unsupported_format_returns_415(client: TestClient):
    resp = _ingest(client, "image.bin", b"\x00\x01\x02", "application/octet-stream")
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "unsupported_format"


def test_empty_document_returns_400(client: TestClient):
    resp = _ingest(client, "empty.txt", b"", "text/plain")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_document"


def test_whitespace_only_document_returns_400(client: TestClient):
    resp = _ingest(client, "ws.txt", b"   \n\t  ", "text/plain")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_document"


def test_delete_unknown_document_returns_404(client: TestClient):
    resp = client.delete("/documents/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_markdown_upload_with_octet_stream_is_inferred(client: TestClient):
    # A .md file sent as octet-stream is inferred to text/markdown and ingested.
    resp = _ingest(client, "notes.md", b"# Title\n\nSome body text here.", "application/octet-stream")
    assert resp.status_code == 201
    assert resp.json()["chunk_count"] >= 1
