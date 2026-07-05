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

    # --- multi-agent layer (Phase 4; all optional / defaulted to preserve keyless boot) ---
    # Max collaboration rounds per Multi_Agent_Run. Resolved to [1, 50] with a bounded
    # default of 6 by the orchestrator when absent/invalid (Req 2.5, 2.6).
    max_rounds: int | None = None
    # Max Critic-driven revision cycles per Multi_Agent_Run. Resolved to [1, 20] with a
    # bounded default of 3 when absent/invalid (Req 3.5, 3.6).
    max_revisions: int | None = None
    # Approval policy governing the Human_Approval_Gate; "auto" is the keyless default so
    # runs complete end-to-end without external human input (Req 5.7).
    approval_policy: Literal["auto", "human"] = "auto"

    # --- enterprise layer (Phase 5; all optional / defaulted to preserve keyless boot) ---
    # Master toggle for the enterprise auth layer. The test suite may set this False.
    auth_enabled: bool = True
    # Access_Token signing secret (Token_Signing_Secret). Optional so keyless local boot
    # succeeds; ``build_auth_service`` generates a per-boot dev secret in the local
    # profile when absent, and ``load_settings`` requires it in the production profile
    # (Req 1.7, 1.8). ``SecretStr`` keeps it out of logs / repr / model_dump.
    jwt_secret: SecretStr | None = None
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_expiry_seconds: int = 3600  # resolved within [60, 86_400] by the Auth_Service

    # --- enterprise: argon2id password / API-key hashing parameters ---
    argon2_time_cost: int = 2  # [1, 10]
    argon2_memory_cost: int = 64 * 1024  # KiB; [8 * 1024, 1_048_576]
    argon2_parallelism: int = 2  # [1, 8]

    # --- enterprise: per-principal rate limiting (Redis-backed) ---
    # ``rate_limit_enabled=False`` forces the NoOp_Rate_Limiter regardless of Redis, so
    # the keyless/test lane is deterministic (Req 6.5).
    rate_limit_enabled: bool = True
    rate_limit_max: int = 60  # [1, 100_000] (Req 6.4)
    rate_limit_window_seconds: int = 60  # [1, 86_400] (Req 6.4)

    # --- observability layer (Phase 6; all optional / defaulted to preserve keyless boot) ---
    # Tracing export (optional; the NoOp_Tracing_Exporter is used when absent). The
    # ``langsmith_api_key`` is the Tracing_Credential; as a ``SecretStr`` it never appears
    # in logs / repr / model_dump (Req 1.2, 10.1). ``tracing_export_enabled`` is a master
    # toggle; the NoOp exporter is still selected whenever no key is configured.
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "agentforge"
    tracing_export_enabled: bool = True

    # Cost model (the default rate is applied when a (provider, model) pair is unlisted).
    # Decimal-as-string so no float drift; the keyless default is free (Req 2.5).
    cost_default_prompt_per_1k: str = "0.0"
    cost_default_completion_per_1k: str = "0.0"
    # Optional JSON rate table, e.g.
    # {"groq:llama-3.1-8b": {"prompt": "0.05", "completion": "0.08"}}.
    cost_rate_table_json: str | None = None

    # Guardrails (deterministic defaults; all optional). ``guardrail_max_input_chars`` is
    # the default max-length input guardrail; ``guardrail_blocklist_json`` an optional
    # static blocklist of terms (Req 5.7, 10.2).
    guardrail_max_input_chars: int = 8000
    guardrail_blocklist_json: str | None = None

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

    def active_tracing_exporter(self) -> str:
        """Return the active Tracing_Exporter name based on credential presence.

        Returns ``"langsmith"`` iff a Tracing_Credential is configured **and** export is
        enabled, else ``"noop"`` — so no external tracer is constructed on the keyless
        path and trace export never occurs without a credential (Req 1.2, 1.4, 10.2).
        """
        return (
            "langsmith"
            if self.tracing_export_enabled and self.langsmith_api_key is not None
            else "noop"
        )


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
        settings = Settings()  # type: ignore[call-arg]
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

    # Phase 5 production guard: the Token_Signing_Secret is optional in the local profile
    # (a dev secret is generated at boot) but REQUIRED in production. Its absence aborts
    # startup before any handler is reachable (Req 1.7, 1.8).
    if (
        settings.profile == "production"
        and settings.auth_enabled
        and settings.jwt_secret is None
    ):
        raise ConfigError(["jwt_secret"], detail="required in production profile")
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (composition-root convenience)."""
    return load_settings()
