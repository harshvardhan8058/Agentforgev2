# Architectural Decision Record — AgentForge Phases 1–2

This document records the rationale for the major architectural decisions in the
Foundation (Phase 1) and Core RAG (Phase 2) of AgentForge, per Requirement 14.3. It
mirrors the "Design Decisions & Why" section of the design document so the reasoning is
discoverable from the repository itself.

## 1. Interfaces at exactly three seams (LLM, Embedding, Vector store)

These are the parts most likely to change as the platform grows or as cost/quality
trade-offs shift. Abstracting **only** these three seams — `LLM_Provider`,
`Embedding_Provider`, and `Vector_Store` — keeps the design simple while guaranteeing
that later phases can swap providers without touching the RAG pipeline. The service
layer depends only on the abstract contracts (`*/base.py`); concrete implementations are
referenced solely by the composition root (`config/container.py`).

_Validates: Requirements 1.2, 11.6._

## 2. Fallback_Provider as the default LLM

The platform owner's guiding constraint is that the system must run and be verifiable
locally **before** any agentic capability is added. A deterministic, network-free
`Fallback_Provider` makes the whole system — and its entire test suite — runnable with
zero credentials. Its determinism also makes it ideal for property-based tests, since
identical inputs always yield identical output.

_Validates: Requirements 11.3, 11.4, 13.3, 14.4._

## 3. Local sentence-transformers embeddings by default (`all-MiniLM-L6-v2`, 384-dim)

The default embedder is free, CPU-friendly, and good enough for retrieval quality in
development. Critically, the pgvector column is sized to the **configured** embedding
dimension, so upgrading to a hosted embedder later is a configuration + migration
change, not a code change. The model loads lazily on first use so importing and
constructing the provider stays cheap and side-effect free.

_Validates: Requirements 4.3, 9.1, 14.4._

## 4. Two profiles (Chroma local / pgvector production), one code path

Chroma removes infrastructure friction for local development, while pgvector
consolidates relational and vector data in one production database. Because both sit
behind the `Vector_Store` interface, the calling code is identical across profiles; the
composition root selects the implementation from the active profile.

_Validates: Requirements 10.1, 10.2, 10.3._

## 5. Credentials always optional; only non-secret settings are required

This makes the system "secure and runnable by default": nothing sensitive is ever
required to boot, and no secret is committed or logged. Credentials are typed as
`SecretStr` so pydantic redacts them from `repr`, `str`, `model_dump`, and logging
output. Required non-secret settings (`database_url`, `redis_url`) are validated at
startup, and a missing one aborts boot while naming the offending key.

_Validates: Requirements 3.2, 3.4, 3.6._

## 6. Character-based chunker with recorded per-boundary overlap

Storing the exact overlap used at each boundary makes the round-trip reconstruction
property unambiguous, even when the final chunk is shorter than the configured overlap —
a subtle case that a naive "subtract a constant overlap" approach gets wrong.
Concatenating the chunks in order while removing the recorded overlap reconstructs the
original chunker-input text exactly.

_Validates: Requirements 8.5, 13.4._

## 7. Markdown: strip by default, preserve optionally

**Decision:** normalize Markdown to plain text before chunking by default
(`markdown_mode=strip`).

**Why:** Markdown markup (`#`, `*`, link syntax, tables) adds tokens that dilute
embedding quality and can fragment semantically related text, so stripping generally
improves retrieval relevance.

**Trade-off:** structure that carries meaning (headings as section labels, code fences)
is lost, and the round-trip property is then defined against the normalized text rather
than the raw bytes. For documents where structure matters, `markdown_mode=preserve`
keeps the raw Markdown and the round-trip holds against the raw input. Making this a
configurable switch lets the platform owner experiment and learn the trade-off directly
rather than baking in one answer.

_Validates: Requirement 8 (chunking), configurable per deployment._

## 8. Grounding-only prompt construction

Building the prompt exclusively from the retrieved chunks (plus a fixed template and the
query) is what makes answers trustworthy and citations verifiable. No content from
outside the retrieved chunks is ever introduced. This is enforced as a correctness
property (Property 11) rather than left to convention.

_Validates: Requirement 12.4._

## 9. Atomic ingestion

The ingestion pipeline commits relational records and vector writes **only after** the
full extract → chunk → embed → store pipeline succeeds. Embeddings are generated before
any store write, and a late write failure rolls back the vector writes. This guarantees
the "persist no Chunks on rejection" requirements and prevents orphaned embeddings.

_Validates: Requirements 7.4–7.6, 9.4._

---

# Architectural Decision Record — AgentForge Phase 3 (Agentic Layer)

This section records the rationale for the major architectural decisions in the Agentic
Layer (Phase 3), per Requirement 14. It mirrors the design document's "Design Decisions
& Why" so the reasoning is discoverable from the repository itself. Phase 3 **reuses —
never reimplements** the Phase 1–2 seams (`LLM_Provider`, `RAG_Service`,
`Embedding_Provider`, `Vector_Store`, the API error envelope, Postgres/pgvector, Redis,
the composition root, and the migration runner).

## 10. LangGraph for the reason → act → observe loop

The agent loop is a small, explicit state machine with conditional termination. Modeling
it as a typed LangGraph `StateGraph` over `AgentState` — rather than an ad-hoc `while`
loop — makes the nodes (`reason`, `act`, `observe`), the edges, the bound, and the two
termination reasons first-class and independently testable. It is also the natural
substrate for the later multi-agent phase: planner/researcher/writer/critic become
additional nodes over the same `AgentState`, added without rewriting the core.

_Validates: Requirements 1.1, 1.7._

## 11. Structural enforcement of the Iteration_Limit

An agent that can loop forever is a stability and cost hazard. The `Iteration_Limit` is
enforced **structurally**: the `observe` node increments the completed-cycle counter by
exactly one, and the conditional edge out of `observe` routes to the `finalize_limit`
terminal the instant the counter reaches the limit, so a new cycle can never push the
count past the bound. Pairing this with an exactly-one-termination-reason invariant makes
"every run ends, and we always know why" a checkable guarantee rather than a hope.
LangGraph's own `recursion_limit` is set as a defensive backstop derived from the limit,
but correctness does not rely on it.

_Validates: Requirements 1.2, 1.4, 1.7, 11.1._

## 12. Tools behind an interface + registry

The orchestrator depends only on the abstract `Tool_Interface` and `Tool_Registry`,
mirroring the Phase 1–2 "interfaces at the seams" rule. A new capability is "implement
`Tool_Interface` + `register`" with zero orchestrator edits. Duplicate-name registration
is rejected so the tool namespace stays unambiguous for selection, and `list_specs`
returns only **available** tools so a disabled tool (e.g. web search without a key) is
never offered to the LLM.

_Validates: Requirements 2.1–2.5, 5.3._

## 13. Reuse of the existing seams

Consuming the existing `LLM_Provider` (reasoning + tool selection), `RAG_Service` (the
`RAG_Tool`), and `Embedding_Provider` + `Vector_Store` (long-term memory) keeps behavior
consistent across phases, avoids duplicated logic, and — crucially — preserves the
keyless promise, because those seams already default to deterministic/local
implementations. All Phase 3 endpoints are added to the existing `API_Service` and use
the existing uniform error envelope.

_Validates: Requirements 4.2, 7.5, 12.1–12.4._

## 14. Text-LLM tool selection with a deterministic fallback

The existing `LLM_Provider.generate` returns text, so the `reason` node asks for a small
JSON decision (`final` or `tool` + arguments) and parses it. For the keyless
`Fallback_Provider`, a pure `Selection_Strategy` chooses tools as a deterministic
function of the run state (prefer the `RAG_Tool` first, then finalize). This keeps the
same node code on both paths while making the whole run reproducible — the foundation for
the fallback-determinism property (identical input → identical answer, tool-call
sequence, and streamed-event sequence).

_Validates: Requirements 1.8, 3.1, 3.5, 9.7._

## 15. Short-term vs long-term memory

Short-term memory is the *bounded working context* of a single run (recent turns +
scratchpad) with a strict `Size_Budget` and FIFO eviction that always retains the current
request — it keeps prompts within limits and prevents runaway context growth. Long-term
memory is *semantic recall across conversations*, which is exactly what the existing
`Embedding_Provider` + `Vector_Store` already do, so we reuse them (under an
`ltm:<conversation_id>` namespace) rather than build a second storage mechanism.

_Validates: Requirements 6.1–6.6, 7.1–7.5._

## 16. SSE over WebSockets for streaming

The agent streams a one-directional sequence of events (steps, tool calls, deltas, one
terminal event) to the client; it needs no bidirectional channel. Server-Sent Events are
simpler, ride on plain HTTP (working through the existing FastAPI `StreamingResponse` and
standard proxies), auto-reconnect on the client, and map cleanly onto the typed event
schema with a single terminal event. The `SSE_Streaming_Service` wraps the run so that
**exactly one** terminal event is emitted — `completion` on success xor a single `error`
on any failure — after which the stream closes. If a later phase needs client→agent
mid-run messaging, a WebSocket transport can be added behind the same `Streaming_Service`
interface without changing the orchestrator.

_Validates: Requirements 9.1–9.9._

## 17. Extension guide — adding a new Tool without modifying the Agent_Orchestrator

Because the orchestrator talks only to `Tool_Registry`/`Tool_Interface`, a new tool is
added purely at the adapter + composition layers:

1. **Implement `Tool_Interface`** in a new module under `tools/` (e.g.
   `tools/calculator_tool.py`). Provide the four members:
   - `name` — a unique, stable string (the registry rejects duplicates).
   - `description` — a human-readable summary the LLM sees when selecting tools.
   - `input_schema` — a JSON-Schema object for the arguments; the `act` node validates
     arguments against it *before* invoking, so a malformed call becomes a contained
     `validation-error` observation rather than a crash.
   - `invoke(arguments) -> Tool_Result` — perform the work; raise `ToolError` on failure
     (the orchestrator contains it as a `tool-execution-error` observation and continues).
   - Optionally override `available` (default `True`) to gate the tool on a credential,
     as `Web_Search_Tool` does — unavailable tools are never offered to the LLM.
2. **Register it in the composition root** (`config/container.py`, in
   `build_tool_registry`): construct the tool with any collaborators it needs (reuse the
   wired providers from `AppContext`) and call `registry.register(...)`. Gate the
   registration on a credential if the tool needs one, following the `Web_Search_Tool`
   pattern.
3. **(If the LLM path should prefer it)** the LLM already discovers the tool via
   `list_specs()`; for the deterministic keyless path, extend or inject a
   `Selection_Strategy` — no orchestrator change is required.

No edit to `agent/orchestrator.py` or `agent/graph.py` is needed at any step.

## 18. Extension guide — adding a new agent node type without modifying the orchestrator core

New node types (e.g. a `plan` node, or the later multi-agent
planner/researcher/writer/critic roles) are added over the same typed `AgentState`:

1. **Add any new state fields** to `AgentState` in `agent/state.py` (plain dataclass
   fields with defaults, so existing construction is unaffected).
2. **Write the node function** as a plain callable `(_state: AgentState) -> dict` in
   `agent/graph.py` (or a new sibling module) that returns the partial state updates it
   produces. Reuse the existing seams (`Tool_Registry`, `Selection_Strategy`,
   `Trace_Recorder`) it depends on — never a concrete provider. Record a `Trace_Entry`
   for observability, exactly as the built-in nodes do, so the new step is visible in the
   ordered trace and streamed events without extra plumbing.
3. **Wire it into the graph** in `build_agent_graph`: `add_node(...)` and the
   `add_edge` / `add_conditional_edges` routing that connects it. Keep the
   iteration-limit edge out of `observe` intact so the bound remains structurally
   enforced.
4. The `Trace_Recorder` and `Streaming_Service` consume the new step automatically
   because they operate on the generic step/entry vocabulary, so a later observability
   phase inspects the new node type without any orchestrator change.

The `Agent_Orchestrator` class itself (which merely builds and runs the compiled graph)
does not change — it discovers the new topology through `build_agent_graph`.

# Phase 4 — Multi-Agent Collaboration & Human Approval

This section extends the decision record with the rationale for the Phase 4
`Multi_Agent_Layer` (Requirement 13). Everything in the layer **reuses, never
reimplements** the Phase 1–3 seams: each Agent_Role runs the existing single-agent
`Agent_Orchestrator`; grounding uses the existing `RAG_Tool`; the streaming, tracing,
persistence, and API layers reuse `Streaming_Service`, `Trace_Recorder`,
`Conversation_Store`, and `API_Service` unchanged.

## 19. A supervisor/graph over agents-as-callers

Modeling the collaboration as an explicit LangGraph `StateGraph` over a typed
`Blackboard_State` — rather than agents that directly call one another — makes routing,
the two bounds, the five termination reasons, and the approval checkpoints first-class
and independently testable. It reuses the exact substrate Phase 3 established (a typed
state plus conditional edges), so the mental model and the testing approach carry
straight over. Agents-as-callers would bury control flow inside each role and make
"every run terminates, and we always know why" unverifiable.

_Validates: Requirements 2, 5, 13.1._

## 20. Bounding both rounds and revisions

Two independent counters guard two independent runaway risks. The revision loop
(Critic ↔ Writer) can oscillate on subjective "not good enough" feedback, so it is
bounded by `Max_Revisions`. `Max_Rounds` is a **global backstop** on total collaboration
rounds — the multi-agent analogue of Phase 3's `Iteration_Limit` — so a future role or a
mis-behaving policy that cycles the graph in other ways still terminates. Both bounds
are enforced structurally in the conditional edges (increment then check), so neither
counter can be pushed past its limit and every run provably terminates with exactly one
`Termination_Reason` from `{completed, max-rounds-reached, max-revisions-reached,
rejected, aborted}`.

_Validates: Requirements 2.2, 2.4, 2.7, 3.1, 3.3, 3.4._

## 21. Agent_Role behind an interface + registry + declarative pipeline

Mirrors the "interfaces at the seams" rule from Phase 1–2 and the Phase 3 `Tool_Registry`.
The `Multi_Agent_Orchestrator` depends only on `Agent_Role_Interface` and a **declarative
pipeline list** (`DEFAULT_PIPELINE`, plain data). A new role is added by (1) implementing
the interface, (2) registering it under a distinct `role_id`, and (3) listing that
`role_id` in the pipeline order — with **no** edit to the orchestrator routing core.
Distinct `role_id`s keep tracing, streaming, and persistence attribution unambiguous.

### Adding a new Agent_Role — step-by-step guide

1. **Implement `Agent_Role_Interface`** in a new module under `multiagent/roles/`
   (e.g. `roles/summarizer.py`). Provide the three abstract members:
   - `role_id` — a unique, stable string. The registry rejects duplicates.
   - `instructions` — the role-scoped instructions injected into the reused
     `Agent_Orchestrator` prompt (so the role never generates text directly).
   - `act(state) -> Blackboard_State` — read the shared state, do this role's real work
     by running the injected `Agent_Orchestrator`, map the result into the appropriate
     blackboard field, and return the updated state.

   A minimal working role:

   ```python
   # multiagent/roles/summarizer.py
   from agentforge.agent.orchestrator import Agent_Orchestrator
   from agentforge.multiagent.roles.base import Agent_Role_Interface
   from agentforge.multiagent.state import Blackboard_State

   class Summarizer_Agent(Agent_Role_Interface):
       def __init__(self, orchestrator: Agent_Orchestrator) -> None:
           # Reuse the SAME existing single-agent orchestrator (Req 11.1).
           self._orchestrator = orchestrator

       @property
       def role_id(self) -> str:  return "summarizer"

       @property
       def instructions(self) -> str:
           return "Summarize the draft in one paragraph for a busy reader."

       def act(self, state: Blackboard_State) -> Blackboard_State:
           request = f"{self.instructions}\n\nDraft:\n{state.draft.content if state.draft else ''}"
           result = self._orchestrator.run(request, conversation_id=state.conversation_id)
           # Attach the summary to a state field of your choice (add one to
           # Blackboard_State if the role produces a new artifact type).
           return state
   ```

2. **Register it in the composition root** (`config/container.py`, in
   `_default_role_registry` or a settings-driven registry): construct the role with
   any collaborators it needs (reuse the wired `Agent_Orchestrator` from `AgentContext`)
   and call `registry.register(...)`. The registry rejects duplicate `role_id`s so a
   collision fails fast.

3. **List its `role_id` in the pipeline** — either edit `DEFAULT_PIPELINE` in
   `multiagent/roles/base.py` (adds the phase globally) or supply a settings-driven
   pipeline list when constructing the `Multi_Agent_Orchestrator`. The graph is built
   generically from the pipeline order, so no edit to `graph.py` or `orchestrator.py`
   is required.

The `Multi_Agent_Orchestrator` class itself (which merely builds and runs the compiled
graph) does not change — it discovers the new topology through the registry and the
pipeline list.

_Validates: Requirements 1.4, 13.2._

## 22. Each role reuses the Phase 3 single-agent orchestrator

Each role's real work — reasoning, tool use, memory — is exactly what the Phase 3
`Agent_Orchestrator` already does. Running that orchestrator inside `act` (rather than
writing a second reasoning loop) keeps behavior consistent, avoids duplicated logic, and
preserves the keyless promise: the orchestrator already defaults to the deterministic
`Fallback_Provider` and the disabled web search, so identical inputs produce identical
role outputs and the whole multi-agent graph stays reproducible end-to-end. The
Researcher gets grounding for free through the already-registered `RAG_Tool`; citations
are produced by the existing RAG pipeline, never reimplemented in the multi-agent layer.

_Validates: Requirements 1.2, 8.1, 8.4, 11.1, 11.2, 11.3, 11.4._

## 23. Human-in-the-loop as an Approval_Policy over a framework-agnostic pause/resume

Approval is expressed as a policy seam (`Human_In_The_Loop_Policy` vs
`Auto_Approve_Policy`) implemented over a small pause/resume abstraction — the
`Human_Approval_Gate` + an in-memory `Checkpoint_Store`. A pause sets the
`awaiting_approval` flag on the blackboard, snapshots the state to the
`Checkpoint_Store`, records an `approval_pause` trace entry, and emits an
`approval_required` streamed event; a resume re-invokes the graph on the snapshot with
the human decision applied.

Because the gate is a **plain in-process abstraction** rather than a hard binding to
LangGraph's interrupt/checkpointer, it stays testable independently of any real human
approver **and** any real graph runtime: tests inject `Approval_Decision`s to exercise
pause → resume with no external input, and the keyless `Auto_Approve_Policy` — the
default when the configuration provides no policy — approves every checkpoint
deterministically so runs complete end-to-end. The LangGraph-integrated variant of the
same seam is a valid future implementation; the interface is what the orchestrator
depends on, not the mechanism.

_Validates: Requirements 5.1, 5.2, 5.4, 5.5, 5.6, 5.7, 12.5, 13.3._

## 24. Multi-agent streaming preserves the Phase 3 single-terminal guarantee

The `Multi_Agent_Streaming_Service` extends only the event **vocabulary**
(`agent_started`, `plan`, `research`, `draft`, `critic_feedback`, `approval_required`,
`completion`, `error`) — not the streaming mechanics. It reuses the Phase 3 SSE frame
shape (`event: <type>\ndata: <json>\n\n`), assigns each event a monotonic `sequence`,
identifies the acting `role_id` on every agent event, and wraps the whole generator body
in a single `try`/`except` so **exactly one** terminal event is emitted per stream —
`completion` carrying the `Final_Output` on success xor a single `error` on failure —
after which the stream closes. `approval_required` is intentionally non-terminal: the
stream ends after it so the run can be resumed on a separate request and re-streamed by
a fresh call. Under the `Fallback_Provider` + `Auto_Approve_Policy`, the event sequence
is deterministic — identical input yields identical ordered events with identical
`role_id` attribution.

_Validates: Requirements 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.8, 7.9._

---

_Scope note:_ this record covers Phases 1–4. Enterprise auth/RBAC/multi-tenancy,
cost/token analytics and evaluation frameworks, the frontend, third-party integrations,
and cloud deployment are reserved for later phases and are enabled — but not designed —
by the modular seams established here.



---

# Phase 5 — Enterprise Controls (Auth, RBAC, Multi-Tenancy, API Keys, Rate Limiting)

This section records the rationale for the Phase 5 `Enterprise_Layer` (Requirement 11).
Everything here **reuses, never reimplements** the Phase 1–4 seams: the FastAPI
`API_Service` and its uniform `AppError` envelope, `Settings` + `load_settings` +
`config/container.py`, Postgres + the migration runner, Redis, and every existing router
and store. The layer is fully runnable and testable **keyless** — an in-memory
Identity_Store + API-key store, a `NoOp_Rate_Limiter`, and a dev-generated `jwt_secret`
back the default lane.

## 25. Argon2id for password and API-key hashing

Passwords and API-key secrets are hashed with **argon2id** via `argon2-cffi`. Argon2id is
the OWASP-recommended default for new systems: it is **memory-hard**, so GPU/ASIC
brute-force is dramatically more expensive per guess than for bcrypt or pbkdf2, and its
cost parameters (`time_cost`, `memory_cost`, `parallelism`) are tunable per environment
through `Settings` (`ARGON2_TIME_COST`, `ARGON2_MEMORY_COST`, `ARGON2_PARALLELISM`). The
library's constant-time `verify` is reused for **both** consumers, so there is exactly
one hashing seam and a plaintext comparison is never performed. Only the irreversible
`password_hash` / `key_hash` is ever persisted — the plaintext password never leaves the
`Auth_Service.register` call frame, and an API-key secret is returned to the caller
**exactly once** at creation and never stored or logged.

_Validates: Requirements 1.1, 1.6, 5.1, 5.2, 8.5, 11.4._

## 26. JWT + a local credential store, behind the `Auth_Service` seam

Local authentication (registration + login + password hashing + JWT issue/verify) is the
simplest correct thing that ships end-to-end today. Issuance and verification live behind
an `Auth_Service` interface whose only backing dependency is the abstract
`Identity_Store`, so a later phase can drop in OAuth/SSO by implementing the same surface
— **no endpoint is rewritten** and no handler knows how tokens are minted or resolved.
Tokens are `PyJWT` HS256 with claims `sub` (user id), `org_id`, `role`, and `exp`.
`Auth_Service.verify` returns `None` for **any** invalid token (bad signature, wrong
secret, expired, malformed) and never raises, so the Principal_Dependency maps `None` to
a uniform `AppError("unauthorized", 401)` and a decode failure can never be mistaken for a
code-path bug.

_Validates: Requirements 1.2, 1.4, 1.5, 9.6, 11.4._

## 27. RBAC as a static role → permission map

Authorization is a pure function of a single static map, `ROLE_PERMISSIONS` in
`enterprise/rbac.py`. The four roles nest strictly `viewer ⊆ member ⊆ admin ⊆ owner` and
every role grants `read`. `RBAC_Policy.is_authorized(role, permission)` simply tests
membership in the mapped set, which makes it trivially testable and keeps every endpoint
ignorant of the mapping. Endpoints declare `Depends(require_permission(Permission.X))` —
a dependency factory that reads the map at request time — so **adding a role or a
permission is a single-file edit** to `ROLE_PERMISSIONS` with no handler change.
Attribute-based access control (ABAC) is more expressive, but Phase 5's requirements are
role-centric, so the simplicity of a static map is the right trade.

_Validates: Requirements 3.1, 3.2, 3.3, 3.5, 3.6, 11.2._

## 28. Tenant isolation enforced at the data-access layer

Handlers are the wrong place to enforce tenancy: any endpoint that forgets a check leaks
data. Instead, every tenant-owned store method takes `org_id` as a **required** parameter
and constrains its SQL with `WHERE org_id = :org_id` (top-level tables) or
`AND parent.org_id = :org_id` (descendants, joined through their parent). A cross-tenant
read/mutate/delete therefore matches **zero rows** — the store returns `None`/`[]` and the
router raises `AppError("not_found", 404)`. Cross-tenant access is **404, never 403**,
because a 403 would leak the fact that a resource exists in another org. Only the
top-level tables (`documents`, `conversations`, `agent_runs`, `multi_agent_runs`) carry an
`org_id` column (migration `0007`); descendants (`chunks`, `messages`, `trace_entries`,
`approval_decisions`, `run_checkpoints`) inherit tenancy through their parent FK, which
avoids two edges of truth to keep in sync while `ON DELETE CASCADE` from `organizations`
still sweeps everything transitively.

_Validates: Requirements 4.1–4.6, 7.3, 7.5, 8.2, 11.3._

## 29. Reusable Principal + Authorization dependencies

`get_current_principal` (in `api/deps.py`) resolves an `Authorization: Bearer <jwt>` or an
`X-API-Key` header to a `Principal` uniformly, derives its `permissions` once from the
role via `RBAC_Policy`, and then applies the per-principal `Rate_Limiter`.
`require_permission(perm)` is a dependency **factory** returning a callable that raises
`AppError("forbidden", 403)` when the principal lacks `perm`. A new endpoint adopts the
whole enterprise contract by declaration alone — no bespoke authorization or tenancy logic
in the handler body.

_Validates: Requirements 1.4, 5.3, 7.1, 7.2, 7.6, 7.7._

## 30. Organization-scoped API keys (create-once, list-metadata, revoke)

An API key is an org-scoped credential for programmatic clients; its permissions derive
from its role through the same `RBAC_Policy`, so a role/permission change propagates to
API-key principals with no extra plumbing. The secret is `af_` + `secrets.token_urlsafe(32)`
(~256 bits of entropy); only an indexed `key_prefix` (first 8 chars) and the argon2
`key_hash` are persisted. Resolution narrows to the tiny prefix-indexed candidate set,
then confirms with a constant-time `verify`; revoked keys are excluded by the
`WHERE revoked_at IS NULL` index, so a revoked or unknown secret resolves to `None` → 401.
The create response carries the plaintext secret **exactly once**; `list` returns metadata
only (never the hash or the secret); and every `*_for_org` store method filters by
`org_id`, so a cross-org list/revoke is a structural 404.

_Validates: Requirements 5.1, 5.2, 5.4, 5.5, 5.6, 5.7._

## 31. Keyless dev boot: generated JWT secret + NoOp limiter + in-memory stores

The Phase 1–4 promise is "runs and tests keyless"; Phase 5 preserves it. When the local
profile omits `JWT_SECRET`, `build_auth_service` generates a per-boot
`secrets.token_urlsafe(64)` (nothing is written to disk, so each restart naturally
invalidates outstanding dev tokens). `build_rate_limiter` selects `NoOp_Rate_Limiter`
whenever `rate_limit_enabled` is false or no Redis client is supplied, and the composition
root builds `InMemory_Identity_Store` + `InMemory_API_Key_Store` outside the production
profile. In **production**, `JWT_SECRET` is required — `load_settings` raises `ConfigError`
before startup if it is missing — and the Redis-backed limiter + Postgres stores are wired
through the **same** seams; only the concretes differ. All Phase 5 secrets and tunables
flow through the existing `Configuration_Manager` (`Settings`); no separate configuration
or persistence mechanism is introduced. The `.env.example` file lists every Phase 5
variable (`AUTH_ENABLED`, `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRY_SECONDS`,
`ARGON2_TIME_COST`, `ARGON2_MEMORY_COST`, `ARGON2_PARALLELISM`, `RATE_LIMIT_ENABLED`,
`RATE_LIMIT_MAX`, `RATE_LIMIT_WINDOW_SECONDS`) with keyless-safe defaults.

_Validates: Requirements 1.7, 1.8, 6.4, 6.5, 9.2, 10.1, 11.4._

## How-to — Adding a new role or permission

The RBAC layer is designed so this touches **exactly one file** and **no endpoint**:

1. **Add the enum member.** In `enterprise/rbac.py`, add the value to `Role` and/or
   `Permission` (e.g. `AUDIT = "audit"`).
2. **Extend the map.** Add or update the entry in `ROLE_PERMISSIONS`, keeping the
   `viewer ⊆ member ⊆ admin ⊆ owner` nesting intact (build the new set from the adjacent
   one, as the existing `_MEMBER = _VIEWER | {...}` pattern does). A brand-new permission
   is granted to whichever roles should hold it; a brand-new role is given a
   `frozenset` of the permissions it grants.
3. **Use it at the seam.** Protect an endpoint with
   `Depends(require_permission(Permission.AUDIT))`. Because `require_permission` reads the
   map at request time, no handler and no `Authorization_Dependency` code changes.
4. **Add a test.** Extend the RBAC property tests (the iff-invariant and the subset
   nesting) — they are parameterized over the enums, so they pick up the new member
   automatically; assert the nesting still holds.

No edit to any router, to `api/deps.py`, or to the `Auth_Service` is required.

## How-to — Adopting auth + tenancy on a new endpoint

A new endpoint inherits authentication, authorization, and tenant isolation by
**declaration**, with no bespoke logic in the handler:

1. **Declare the principal + permission.** Add
   `principal: Principal = Depends(require_permission(Permission.X))` to the handler
   signature. This resolves the credential (401 if missing/invalid), enforces the
   permission (403 if the role lacks it), and applies the rate limiter — all before the
   handler body runs.
2. **Thread `principal.org_id` into the store.** Pass `principal.org_id` (or the
   `get_org_id` shortcut) into the org-scoped store/service call. The store constrains
   its query by `org_id`, so a cross-tenant resource returns `None`/`[]` and the handler
   raises `AppError("not_found", 404)` — never a bespoke tenant check, never a 403.
3. **On create, pass `principal.org_id`.** The store's `create` signature requires
   `org_id`, so a resource can only be created within the caller's tenant.

That is the entire contract; the store is the enforcement point, so a forgotten check can
never leak another tenant's data.

_Validates: Requirements 11.1, 11.2, 11.3, 11.4._
