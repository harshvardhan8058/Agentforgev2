"""Unit tests for the composition root / provider-selection logic.

Assert local vs production and key-present vs keyless selection, and that a new
LLM_Provider can be registered without changing the RAG_Service (Req 10.2, 10.3, 11.2,
11.3, 11.6). All tests run keyless — the default embedder is constructed but never
loads a model (lazy), so no download occurs.
"""

from __future__ import annotations

from agentforge.config.container import (
    build_embedding_provider,
    build_llm_provider,
    build_vector_store,
)
from agentforge.config.settings import Settings
from agentforge.embeddings.base import Embedding_Provider
from agentforge.embeddings.sentence_transformer import SentenceTransformer_Embeddings
from agentforge.llm.base import GenerationResult, LLM_Provider
from agentforge.llm.fallback_provider import Fallback_Provider
from agentforge.vectorstore.chroma_store import Chroma_Store

_BASE = {
    "database_url": "postgresql+asyncpg://u:p@localhost:5432/db",
    "redis_url": "redis://localhost:6379/0",
}


def _settings(**overrides) -> Settings:
    return Settings(**{**_BASE, **overrides})


# --- LLM selection ----------------------------------------------------------------


def test_llm_defaults_to_fallback_when_keyless():
    """No credential -> Fallback_Provider (Req 11.3)."""
    provider = build_llm_provider(_settings())
    assert isinstance(provider, Fallback_Provider)
    assert provider.name == "fallback"


def test_llm_selects_groq_when_key_present():
    """A Groq credential -> the "groq" builder is selected (Req 11.2).

    A fake groq builder is injected so selection is verified without the real client.
    """

    class _FakeGroq(LLM_Provider):
        @property
        def name(self) -> str:
            return "groq"

        def generate(self, prompt: str) -> GenerationResult:
            return GenerationResult(text="ok", provider="groq")

    settings = _settings(groq_api_key="secret-key")
    assert settings.active_llm() == "groq"

    provider = build_llm_provider(settings, llm_registry={"groq": lambda _s: _FakeGroq()})
    assert isinstance(provider, _FakeGroq)
    assert provider.name == "groq"


def test_new_llm_provider_can_be_registered_without_touching_rag_service():
    """A brand-new provider implementing the interface can be slotted in (Req 11.6)."""

    class _CustomProvider(LLM_Provider):
        @property
        def name(self) -> str:
            return "custom"

        def generate(self, prompt: str) -> GenerationResult:
            return GenerationResult(text="custom", provider="custom")

    # Register under the "fallback" selection name to prove selection is registry-driven
    # and the returned object is a valid LLM_Provider usable anywhere the interface is.
    settings = _settings()
    provider = build_llm_provider(
        settings, llm_registry={"fallback": lambda _s: _CustomProvider()}
    )
    assert isinstance(provider, _CustomProvider)
    assert isinstance(provider, LLM_Provider)


# --- Embedding selection ----------------------------------------------------------


def test_embedding_defaults_to_local_sentence_transformer_keyless():
    """Keyless -> SentenceTransformer_Embeddings default (Req 14.4)."""
    provider = build_embedding_provider(_settings())
    assert isinstance(provider, SentenceTransformer_Embeddings)
    assert provider.dimension == 384


def test_embedding_selects_hosted_when_configured_and_keyed():
    """embedding_provider=hosted + key -> hosted builder selected."""

    class _FakeHosted(Embedding_Provider):
        @property
        def dimension(self) -> int:
            return 1536

        def embed_text(self, text: str):
            return [0.0] * 1536

        def embed_batch(self, texts):
            return [[0.0] * 1536 for _ in texts]

    settings = _settings(
        embedding_provider="hosted", hosted_embedding_api_key="hk"
    )
    provider = build_embedding_provider(
        settings, embedding_registry={"hosted": lambda _s: _FakeHosted()}
    )
    assert isinstance(provider, _FakeHosted)


def test_embedding_falls_back_to_local_when_hosted_selected_but_keyless():
    """embedding_provider=hosted but no key -> local default (credentials optional)."""
    settings = _settings(embedding_provider="hosted")  # no hosted key
    provider = build_embedding_provider(settings)
    assert isinstance(provider, SentenceTransformer_Embeddings)


# --- Vector store selection -------------------------------------------------------


def test_vector_store_local_profile_uses_chroma():
    """Local profile -> Chroma_Store (Req 10.2)."""
    settings = _settings(profile="local")
    emb = SentenceTransformer_Embeddings()
    store = build_vector_store(settings, emb)
    assert isinstance(store, Chroma_Store)


def test_vector_store_production_profile_uses_pgvector():
    """Production profile -> the pgvector builder is selected (Req 10.3)."""

    class _FakePgvector(Chroma_Store):
        pass

    settings = _settings(profile="production")
    assert settings.active_vector_store() == "pgvector"
    emb = SentenceTransformer_Embeddings()
    store = build_vector_store(
        settings,
        emb,
        vector_store_registry={"pgvector": lambda _s, e: _FakePgvector(dim=e.dimension)},
    )
    assert isinstance(store, _FakePgvector)
