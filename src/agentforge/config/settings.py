"""Configuration_Manager.

Loads all application settings from environment variables (Req 3.1), treats every
credential as optional (Req 3.2), validates required non-secret settings at startup
and aborts naming the offending key when one is missing (Req 3.3, 3.4), and never
exposes secret values in logs or error output (Req 3.6).

Credentials use ``SecretStr`` so that pydantic redacts them from ``repr``, ``str``,
``model_dump``, and logging output by default.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(RuntimeError):
    """Raised when required non-secret configuration is missing or invalid.

    The message names the offending setting(s) so startup failures are actionable
    (Req 3.4). It never contains secret values.
    """

    def __init__(self, missing: list[str], detail: str = "") -> None:
        self.missing = missing
        joined = ", ".join(missing)
        msg = f"Missing or invalid required setting(s): {joined}"
        if detail:
            msg = f"{msg} ({detail})"
        super().__init__(msg)


class Settings(BaseSettings):
    """Typed application settings sourced exclusively from the environment."""

    model_config = SettingsConfigDict(
        env_file=None,  # env-only loading; .env is a developer convenience via Docker.
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- profile / non-secret required settings ---
    profile: Literal["local", "production"] = "local"
    api_port: int = 8000

    # --- chunking ---
    chunk_max_chars: int = 1000  # max chunk size
    chunk_overlap_chars: int = 150  # overlap between consecutive chunks
    markdown_mode: Literal["strip", "preserve"] = "strip"

    # --- embeddings ---
    embedding_provider: Literal["sentence_transformer", "hosted"] = "sentence_transformer"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # --- retrieval ---
    top_k_default: int = 4  # must resolve within [1, 10]
    top_k_min: int = 1
    top_k_max: int = 10

    # --- ingestion limits ---
    max_document_bytes: int = 50 * 1024 * 1024  # 50 MB
    extraction_timeout_seconds: int = 30

    # --- infrastructure (required non-secret) ---
    # These have no default: they MUST be provided at startup or boot aborts.
    database_url: str = Field(...)  # e.g. postgresql+asyncpg://user:pass@host/db
    redis_url: str = Field(...)

    # --- agentic layer (Phase 3; all optional / defaulted to preserve keyless boot) ---
    # Max reason->act->observe cycles per Agent_Run. Resolved to [1, 100] with a
    # bounded default of 10 by the orchestrator when absent/invalid (Req 1.5, 1.6).
    iteration_limit: int | None = None
    # Short_Term_Memory Size_Budget as a positive token/character count (Req 6.2, 6.3).
    memory_size_budget: int | None = None
    # Pluggable web-search provider selection; "disabled" is the keyless default so no
    # network request is ever made without a credential (Req 5.2, 5.4).
    search_provider: Literal["disabled", "tavily"] = "disabled"

    # --- credentials (ALL optional) ---
    groq_api_key: SecretStr | None = None
    hosted_embedding_api_key: SecretStr | None = None
    # Absence disables the Web_Search_Tool entirely (Req 5.4).
    search_api_key: SecretStr | None = None

    def active_llm(self) -> str:
        """Return the active LLM provider name based on credential presence."""
        return "groq" if self.groq_api_key else "fallback"

    def active_search(self) -> str:
        """Return the active search provider name based on credential presence.

        Falls back to ``"disabled"`` whenever no ``search_api_key`` is configured, so
        the Web_Search_Tool degrades gracefully and performs no network request in the
        keyless default (Req 5.2, 5.4).
        """
        return self.search_provider if self.search_api_key else "disabled"

    def active_vector_store(self) -> str:
        """Return the active vector store based on the selected profile."""
        return "pgvector" if self.profile == "production" else "chroma"


# Required non-secret settings that must be present at startup. Anything with a
# default is considered satisfied; these two have no default and drive Req 3.3/3.4.
_REQUIRED_NON_SECRET = ("database_url", "redis_url")


def load_settings() -> Settings:
    """Load and validate settings, aborting with the offending key on failure.

    Raises:
        ConfigError: if a required non-secret setting is missing or invalid. The
            error names the missing setting(s) and never includes secret values.
    """
    try:
        return Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        missing: list[str] = []
        for err in exc.errors():
            loc = err.get("loc", ())
            name = str(loc[0]) if loc else "<unknown>"
            missing.append(name)
        # De-duplicate while preserving order.
        seen: set[str] = set()
        ordered = [m for m in missing if not (m in seen or seen.add(m))]
        raise ConfigError(ordered) from None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (composition-root convenience)."""
    return load_settings()
