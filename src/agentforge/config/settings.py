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

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
)
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

    # Persist the ten Domain_Stores to the running Postgres over a DSN (no credential).
    # Default False so the keyless unit lane stays in-memory and deterministic (Req 10.1).
    # The composition root consults ``persist_domain_stores()`` (below), which is ON when
    # this flag is set OR in the production profile — so production behavior is unchanged
    # and the local stack opts in explicitly via ``USE_DATABASE=true`` in compose.
    use_database: bool = False

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

    # When retrieval finds nothing, `/query` returns a fixed "no grounding" answer and
    # never calls the LLM (Req 12.5) — the safe default that keeps every answer
    # document-backed and verifiable.
    #
    # Enabling this lets that specific case fall through to a general-knowledge answer
    # instead, so the assistant can also field questions the corpus does not cover.
    # Such answers are ALWAYS returned with ``grounded=False`` and zero citations, and
    # are built from a separate template, so a model-knowledge answer can never be
    # mistaken for a document-backed one. Defaults to ``False``: opting in is a
    # deliberate deployment decision, not an accident.
    allow_ungrounded_answers: bool = False

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

    # --- outbound webhooks ---
    # Bounds on a delivery, all applied per attempt / per event (webhooks/emitter.py). Kept
    # small on purpose: a delivery runs in a background task holding a worker thread, so a
    # pathological consumer must not be able to occupy one for long.
    #
    # The ranges are enforced rather than documented, because these three settings ARE the
    # mechanism that keeps a pathological consumer cheap. Left unvalidated,
    # `WEBHOOK_MAX_ATTEMPTS=1000` with `WEBHOOK_TIMEOUT_SECONDS=600` would be accepted, and a
    # single event would then be able to occupy a worker thread for days. The upper bounds are
    # the point; the lower bounds keep the feature meaningful (one attempt, a real timeout).
    webhook_max_attempts: int = Field(default=3, ge=1, le=10)
    webhook_timeout_seconds: float = Field(default=4.0, gt=0.0, le=30.0)
    webhook_backoff_seconds: float = Field(default=0.5, ge=0.0, le=10.0)

    # --- cost governance: spend budgets ---
    # How long a computed month-to-date spend is reused before recomputing. The budget check
    # runs before every agent/RAG request, so this keeps a SUM over the tenant's month off the
    # request path; the cost is a bounded overshoot within the window (docs/CONFIGURATION.md).
    budget_cache_seconds: float = 30.0

    # --- enterprise: audit trail ---
    # Failure posture for an audit write. False (default) = fail OPEN: a failed write is
    # logged at ERROR and the audited request still succeeds, because an audit store outage
    # must not become a platform outage. True = fail CLOSED: the request fails, which is what
    # a regulated deployment needs when an unrecorded action is worse than a refused one.
    audit_log_required: bool = False

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

    # Vendor-neutral OTLP export (an OpenTelemetry Collector, Tempo, Jaeger, Honeycomb,
    # ...). Selected only when an endpoint is configured, so the keyless path is unchanged.
    # ``otel_headers`` follows the OTLP convention ("k=v,k2=v2") and may carry an ingest
    # key, so it is a SecretStr and never appears in logs or model_dump.
    # The OpenTelemetry spec's own variable names are accepted as aliases, because a pod
    # with a collector sidecar typically has OTEL_EXPORTER_OTLP_ENDPOINT injected already.
    # Without the alias that deployment would configure nothing, get no export, and get no
    # warning either — a silent no-op is the worst possible outcome for a telemetry setting.
    otel_exporter_endpoint: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "otel_exporter_endpoint", "otel_exporter_otlp_endpoint"
        ),
    )
    otel_service_name: str = "agentforge"
    otel_headers: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("otel_headers", "otel_exporter_otlp_headers"),
    )

    # Cost model (the default rate is applied when a (provider, model) pair is unlisted).
    # Decimal-as-string so no float drift; the keyless default is free (Req 2.5).
    cost_default_prompt_per_1k: str = "0.0"
    cost_default_completion_per_1k: str = "0.0"
    # Optional named rate preset shipped with the platform (see
    # ``observability/cost_presets.py``), e.g. "groq-public-2026-07". Unset means no
    # preset, which keeps the keyless stack free and deterministic. An unknown name is a
    # startup error, not a silent fallback.
    cost_rate_preset: str | None = None
    # Optional JSON rate table, e.g.
    # {"groq:llama-3.1-8b": {"prompt": "0.05", "completion": "0.08"}}. Entries here
    # override the preset for the same (provider, model) pair.
    cost_rate_table_json: str | None = None

    # Guardrails (deterministic defaults; all optional). ``guardrail_max_input_chars`` is
    # the default max-length input guardrail; ``guardrail_blocklist_json`` an optional
    # static blocklist of terms (Req 5.7, 10.2).
    guardrail_max_input_chars: int = 8000
    guardrail_blocklist_json: str | None = None

    # Per-completion budget for the hosted LLM provider. Every call is bounded because a
    # single agent run issues many completions in sequence and a multi-agent run
    # multiplies that by its roles and rounds — one unbounded call is enough to make the
    # whole synchronous request appear to hang.
    llm_timeout_seconds: float = 30.0
    llm_max_retries: int = 2

    # Total time one completion may spend waiting out an upstream rate limit (HTTP 429)
    # before failing with an actionable message. Free hosted tiers meter tokens per
    # minute and a multi-role run can exhaust that on its own; the limit clears in
    # seconds, so a short bounded wait turns a dead run into a slightly slower one.
    llm_rate_limit_max_wait_seconds: float = 8.0

    # Model the Groq provider requests. Exposed because the cost presets price models
    # individually: without it, only the provider's built-in default was ever reachable,
    # so a priced row for any other model was documentation rather than configuration.
    # Blank/unset keeps the provider's own default.
    groq_model: str | None = None

    # --- credentials (ALL optional) ---
    groq_api_key: SecretStr | None = None
    hosted_embedding_api_key: SecretStr | None = None
    # Absence disables the Web_Search_Tool entirely (Req 5.4).
    search_api_key: SecretStr | None = None

    # --- integrations (Phase 8; all optional / defaulted to preserve keyless boot) ---
    # Per-integration Credentials: optional ``SecretStr``, env-only, absent by default, so
    # every integration is Disabled and the platform boots with zero integration
    # credentials (Req 3.3, 3.8, 4.1). ``SecretStr`` keeps them out of logs / repr /
    # model_dump (Req 4.2). Note Slack's credential is a bot token named ``slack_bot_token``.
    slack_bot_token: SecretStr | None = None
    gmail_token: SecretStr | None = None
    google_drive_token: SecretStr | None = None
    github_token: SecretStr | None = None

    # Per-integration Enable_Settings: non-secret master toggles, default True (mirroring
    # ``tracing_export_enabled``). A present Credential + a toggle set False ⇒ Disabled, so
    # an operator can hold an Integration Disabled even when its Credential is present
    # (Req 3.5, 3.6, 3.7). Kept separate from Credential presence.
    slack_enabled: bool = True
    gmail_enabled: bool = True
    google_drive_enabled: bool = True
    github_enabled: bool = True

    # Bounded, keyless-safe execution limits shared by every Integration_Tool (Req 6.4).
    integration_timeout_seconds: int = 10  # Timeout_Budget for a single invocation
    integration_max_results: int = 20  # single-invocation result-count cap (Req 6.3)

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

    def persist_domain_stores(self) -> bool:
        """Return whether the Domain_Stores are DB-backed (persistent) vs in-memory.

        DB-backed when persistence is explicitly enabled via ``use_database`` OR the
        production profile is selected. This splits *persistence* from *profile*: the
        keyless local stack can persist to the already-running Postgres over a DSN (no
        credential) while the deterministic keyless unit lane — which never sets
        ``USE_DATABASE`` and defaults ``profile == "local"`` — stays in-memory (Req 1.1,
        1.3, 10.1). Mirrors the existing ``active_*`` selector helpers.
        """
        return self.use_database or self.profile == "production"

    def integration_enabled(self, name: str) -> bool:
        """Return whether the named integration is Enabled (Req 3.4, 3.6, 3.7).

        Enabled ⇔ the Credential is present AND the Enable_Setting is not ``false``;
        Disabled otherwise. This is a pure, total function of configuration alone —
        independent of any Integration_Connection persistence — mirroring
        ``active_search()``. It is the single enablement authority used by both the
        composition root's connector selection and the Integration_Status service.

        Args:
            name: one of ``"slack"``, ``"gmail"``, ``"google_drive"``, ``"github"``.
        """
        credential_attr = "slack_bot_token" if name == "slack" else f"{name}_token"
        credential = getattr(self, credential_attr)
        toggle = getattr(self, f"{name}_enabled")
        return credential is not None and toggle is not False

    @field_validator(
        "cost_rate_preset",
        "cost_rate_table_json",
        "groq_model",
        "otel_exporter_endpoint",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """Treat an empty/whitespace-only string as "unset" for optional string settings.

        Environment-driven configuration cannot distinguish "absent" from "present but
        empty": a blank line in an `.env` template, Compose `${VAR}` interpolation with
        the variable unset, `--env-file`, and CI all deliver ``""``. Without this,
        ``COST_RATE_PRESET=`` would be validated as a *misspelled preset name* and abort
        startup, so shipping the setting in a template with no value would ship an
        unbootable deployment.
        """
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    def allow_loopback_webhooks(self) -> bool:
        """Whether a webhook URL may target loopback (http://localhost:9000).

        True outside the production profile only, so a developer can build a consumer locally
        while production keeps the SSRF policy intact. Derived rather than configured: an
        operator cannot switch it on for a production deployment by accident.
        """
        return self.profile != "production"

    def active_tracing_exporter(self) -> str:
        """Return the active Tracing_Exporter name based on configuration presence.

        Resolution, in order:

        * ``"noop"`` when ``tracing_export_enabled`` is false, or when neither destination
          is configured — so no external tracer is constructed on the keyless path and
          trace export never occurs without explicit configuration (Req 1.2, 1.4, 10.2);
        * ``"langsmith"`` when a Tracing_Credential is present. It takes precedence for
          compatibility: a deployment that already sets ``LANGSMITH_API_KEY`` must keep
          exporting exactly where it did before this setting existed;
        * ``"otlp"`` when an OTLP endpoint is configured.

        Exactly one destination is active. Fanning out to several would need a composite
        exporter and a way to report partial failure, neither of which any caller asks for
        yet; configuring both is therefore reported at startup rather than silently
        halving the export.
        """
        if not self.tracing_export_enabled:
            return "noop"
        if self.langsmith_api_key is not None:
            return "langsmith"
        if self.otel_exporter_endpoint:
            return "otlp"
        return "noop"


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

    # A misspelled cost preset must abort startup, not quietly leave the deployment
    # unpriced: reported costs are only trustworthy if the rates behind them were the
    # ones the operator asked for. Validated here — the single configuration gate — so
    # the failure names the setting instead of surfacing later from the cost model.
    #
    # Truthiness, not ``is not None``: an EMPTY value means "unset", and empty values are
    # everywhere in this deployment model — a blank line in an `.env` template, Compose
    # `${VAR}` interpolation with the variable unset, `--env-file`, CI. Treating `""` as
    # a misspelled preset name would make a blank optional setting an unbootable API.
    if settings.cost_rate_preset:
        # Local import: the preset catalogue imports nothing from this module at import
        # time, but keeping it lazy holds settings free of observability dependencies.
        from agentforge.observability.cost_presets import RATE_PRESETS, preset_names

        if settings.cost_rate_preset not in RATE_PRESETS:
            raise ConfigError(
                ["cost_rate_preset"],
                detail=f"unknown preset; known presets: {', '.join(preset_names())}",
            )
    return settings


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (composition-root convenience)."""
    return load_settings()
