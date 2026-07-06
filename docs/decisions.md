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



---

# Phase 6 — Production Observability (Tracing Export, Token/Cost Analytics, Prompt Registry, Guardrails, Evaluation)

This section records the rationale for the Phase 6 `Observability_Layer` (Requirement 12).
Everything here **reuses, never reimplements** the Phase 1–5 seams: the async FastAPI
`API_Service` and its uniform `AppError` envelope, `Settings` + `load_settings` +
`config/container.py`, Postgres + pgvector + the versioned migration runner, Redis, the
pluggable `LLM_Provider` seam with the deterministic keyless `Fallback_Provider`, the
`Trace_Recorder` + `Trace` (consumed, not reimplemented, by the exporter), and the Phase 5
enterprise layer — the `Principal`, `get_current_principal` + `require_permission`
dependencies, the static `RBAC_Policy`, and the request-scoped tenancy context. The layer
is fully runnable and testable **keyless**: with no `Tracing_Credential` and no external LLM
credential, `settings.active_tracing_exporter() == "noop"`, the wired provider is the
`Fallback_Provider` wrapped by the `Instrumented_Provider`, the `Default_Cost_Model` uses its
deterministic default rate, the default guardrails and evaluators are pure functions, and the
usage/prompt/evaluation stores are in-memory.

## 32. A decorator over the `LLM_Provider` seam for usage capture

Usage and cost emission is a cross-cutting concern that must apply to **every** provider
without changing the `generate(prompt) -> GenerationResult` contract or editing any concrete
provider. Modeling it as a decorator — `Instrumented_Provider` *implements* `LLM_Provider`
and wraps another `LLM_Provider` — is the minimal way to achieve this. It is wired **in the
composition root** in place of the bare provider inside `build_app_context`, so Groq and
Fallback are instrumented identically and every downstream RAG/agent/multi-agent flow emits
usage transparently. Callers cannot tell they are talking to a wrapper because the wrapper
exposes the wrapped provider's `name` and the same `generate` signature. Critically,
**delegation happens before emission** and the emission block is wrapped in a guard that
swallows any exception, so a `Usage_Sink` failure can never turn a successful generation into
an error — the wrapped result is always returned unchanged. The token count on the keyless
path is `deterministic_token_count(prompt, result)`, a pure function of the request/response
text, so with the `Fallback_Provider` the emitted `Usage_Record` is fully deterministic, and
`total_tokens = prompt_tokens + completion_tokens` holds by construction.

_Validates: Requirements 2.1, 2.4, 2.7, 7.1, 7.2, 7.7, 9.2._

## 33. The `Tracing_Exporter` as a consumer of the existing `Trace`, with suppressed failures

Trace *recording* is already solved by the Phase 3/4 `Trace_Recorder`; export is a read-side
concern layered on top. Reimplementing recording would duplicate logic and risk drift, so the
`Tracing_Exporter` **consumes** the already-recorded `Trace` and forwards it to an external
destination, never recording steps itself. It is invoked at run completion — off the critical
path, after the run's result is produced — and tags the exported trace with the acting
`Principal`'s `org_id` and `user_id`. The `export` method wraps its forward in a `try/except`
that **suppresses** any external error, guaranteeing that trace export never changes the
outcome of a run. `NoOp_Tracing_Exporter` is the keyless default so **no external call is ever
made without a credential**; `build_tracing_exporter(settings)` selects the LangSmith-backed
exporter only when `active_tracing_exporter() == "langsmith"` (a `Tracing_Credential` is
present and export is enabled). A new exporter is added by implementing the interface and
registering a builder — no orchestrator or recorder edit.

_Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.7, 9.1._

## 34. Immutable, monotonically-versioned prompts with a DB uniqueness constraint

Safe prompt evolution requires that a version, once referenced by a run, can never change
underneath it. A `Prompt_Version` is therefore **append-only**: there is no update path,
`create_version` computes `max(version)+1` per `(org_id, name)` (or `1` for the first), and
the database `UNIQUE (template_id, version)` constraint makes a duplicate version
**structurally impossible** even under concurrent creates. This makes both immutability and a
contiguous `1..N` sequence with no gaps or duplicates a structural guarantee rather than a
convention; `list_versions` returns the numbers ascending and `get_latest` returns the highest.
Rendering is a pure function that **fails closed**: supplying every declared variable produces
the substituted string, while omitting any declared variable raises
`AppError("missing_variable", 400, {"missing": [...]})`, so a half-substituted prompt never
reaches a model.

_Validates: Requirements 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.9, 8.6._

## 35. An ordered guardrail pipeline with allow/flag/block and a block short-circuit

Guardrails must be composable and their combination predictable. The `Guardrail_Pipeline`
evaluates guardrails in a **stable configured order**, accumulates flags, and **stops at the
first block**. This yields a single, testable semantics: `ALLOW` when every guardrail allows;
`ALLOW` carrying all accumulated flags when some flag and none block; and `BLOCK` with the
reason when a guardrail blocks, with no guardrail evaluated after the first block. Applied at
the query/agent/multi-agent entry points via the reusable `apply_input_guardrail(pipeline,
content, downstream)` helper, a blocking **input** raises `AppError("guardrail_blocked", 400,
{"reason": ...})` and the downstream `LLM_Provider`/agent/multi-agent orchestrator is
**never** invoked — the safety guarantee — while the **output** pipeline annotates the
response with flags without blocking — the observability guarantee. The default guardrails
(non-empty, max-input-length, static blocklist) are pure functions of the content, so the
keyless path stays deterministic, and a new guardrail is a composition-root registration with
no entry-point edit.

_Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8._

## 36. Deterministic evaluation on the keyless `Fallback_Provider` with pure evaluators

The value of an evaluation harness for learning and CI is **reproducibility**: the same
dataset + evaluators must yield the same scores every time, with no credential. The
`Evaluation_Framework` runs the real RAG/agent pipeline but through the injected keyless
`pipeline_runner` (the `Fallback_Provider`, a pure function of its prompt), and every
evaluator (`Exact_Match`, `Contains`, `Heuristic`) is a pure function of
`(input, expected, actual)`. The `Aggregate_Score` is the mean of the per-item scores. This
makes an `Evaluation_Run` bit-for-bit repeatable, so both the determinism guarantee and the
aggregate-equals-aggregation invariant are checkable. Datasets, items, and runs are all
`org_id`-scoped, so a cross-tenant dataset or run resolves to `AppError("not_found", 404)`. A
new evaluator is registered in the composition root without touching the run logic.

_Validates: Requirements 6.2, 6.3, 6.4, 6.5, 6.6, 6.8, 6.9._

## 37. `Decimal` cost and a total `Cost_Model` with a default rate

Money must not suffer float rounding, so `Cost` is a `Decimal` throughout and the
`usage_records.cost` column is `NUMERIC(20,8)`. The `Cost_Model` is defined over its
**entire** input space: `Default_Cost_Model` holds a per-1K-token rate table keyed by
`(provider, model)` and falls back to a configured `default_rate` for any unlisted pair, so a
new or misconfigured model never produces an undefined cost or a crash on the hot path. The
computation is exact: `prompt/1000 * prompt_per_1k + completion/1000 * completion_per_1k` in
`Decimal`. The keyless default rate is `0.0`, keeping keyless usage records deterministic, and
a new `Cost_Model` is registered in the composition root without touching the
`Instrumented_Provider` or the `LLM_Provider` contract.

_Validates: Requirements 2.2, 2.5, 2.6._

## 38. Tenant isolation enforced at the data-access layer (404, never 403)

Consistent with Phase 5, tenancy for every observability resource is enforced **at the store,
not the handler**, because any endpoint that forgets a check leaks data. Every Phase 6 store
method (`Usage_Store`, `Prompt_Store`, `Evaluation_Store` and their `InMemory_*` / `Pg_*`
implementations) takes `org_id` as a **required** parameter and constrains its query with
`WHERE org_id = :org_id` (and, for descendants, through the parent FK), so a cross-tenant
read/mutate matches **zero rows** → `None`/`[]` → `AppError("not_found", 404)`. Cross-tenant
access is **404, never 403**, because a 403 would leak the fact that a resource exists in
another org. Every new table (`usage_records`, `prompt_templates`, `prompt_versions`,
`evaluation_datasets`, `evaluation_items`, `evaluation_runs`, `evaluation_results`) carries
`org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE`, so deleting an org
sweeps its observability state transitively. Because the store cannot return cross-org rows,
the handler cannot forget the check.

_Validates: Requirements 10.3, 10.4, 10.5._

## How-to — Adding a new `Tracing_Exporter` without modifying any core flow

Export lives entirely behind the `Tracing_Exporter` interface, so a new tracer is an
adapter + composition edit only:

1. **Implement `Tracing_Exporter`** in a new module under `observability/` (e.g.
   `tracing_exporter.py` or a sibling). Provide the two members:
   - `name` — a stable string identifying the exporter (e.g. `"otel"`).
   - `export(trace, *, org_id, user_id) -> None` — map the consumed `Trace` to the external
     run/span shape, tag it with `org_id`/`user_id` metadata, and **wrap the forward in a
     `try/except` that suppresses any exception** — suppression is the contract, so export can
     never change a run's outcome. Never record steps here; the `Trace` is already produced by
     the reused `Trace_Recorder`.
2. **Select it in the composition root** (`config/container.py`, `build_tracing_exporter`):
   extend the selection so your exporter is returned when its credential/toggle is present,
   keeping `NoOp_Tracing_Exporter` as the keyless default so no external call is made without a
   credential. Add any new credential/toggle to `Settings` as an optional `SecretStr` / bounded
   field so keyless boot is preserved.

No edit to either orchestrator, to the `Trace_Recorder`, or to any router is required.

## How-to — Adding a new `Cost_Model` without modifying the `Instrumented_Provider`

The `Instrumented_Provider` and `Usage_Recorder` depend only on the abstract `Cost_Model`:

1. **Implement `Cost_Model`** in `observability/cost.py` (or a sibling): provide
   `cost_for(provider, model, tokens) -> Decimal`. Keep it **total** — return a defined,
   non-negative `Decimal` for every `(provider, model, Token_Count)`, including unlisted pairs
   (fall back to a default rate) — so the hot path never raises. Use `Decimal` arithmetic
   throughout; never `float`.
2. **Select it in the composition root** (`config/container.py`, `build_cost_model`):
   construct your model from `Settings` and return it. The `Usage_Recorder` receives it by
   injection, so neither the `Instrumented_Provider` nor the `LLM_Provider` contract changes.

## How-to — Adding a new `Guardrail` without modifying any entry point

Guardrails compose behind the `Guardrail` interface and the `Guardrail_Pipeline`:

1. **Implement `Guardrail`** in `observability/guardrails/` (e.g. `defaults.py` or a sibling):
   provide `name` and `check(content) -> Guardrail_Result` returning `ALLOW`, `FLAG` (with
   annotations), or `BLOCK` (with a reason). Keep `check` a **pure function of `content`** so
   the keyless path stays deterministic.
2. **Add it to the pipeline in the composition root** (`config/container.py`,
   `build_guardrail_pipeline`): insert it at the desired position in the ordered guardrail list.
   Order matters — the pipeline evaluates in order and short-circuits at the first `BLOCK`.

Because the query/agent/multi-agent entry points call the pipeline through
`apply_input_guardrail(...)`, no handler or orchestrator changes when a guardrail is added.

## How-to — Adding a new `Evaluator` without modifying the run logic

Evaluators sit behind the `Evaluator` interface consumed by the `Evaluation_Framework`:

1. **Implement `Evaluator`** in `observability/evaluation/evaluators.py`: provide `name` and
   `score(*, input, expected, actual) -> float` as a **pure function of its inputs**, so
   repeated runs on the keyless path are identical.
2. **Register it in the composition root** (`config/container.py`,
   `build_evaluation_framework`): add it to the `evaluators` mapping keyed by its name. A run
   references it by name in `evaluator_names`; the framework loads the org-scoped dataset,
   produces each item's actual output via the keyless `pipeline_runner`, scores with each named
   evaluator, and persists the run — no change to `framework.py` is required.

## How-to — How the `Instrumented_Provider` captures usage without breaking the contract or the keyless promise

The instrumentation is invisible to callers and to the keyless lane by design:

1. **It implements `LLM_Provider`.** `Instrumented_Provider` exposes the wrapped provider's
   `name` and the same `generate(prompt) -> GenerationResult`, so RAG_Service and the
   orchestrators see no signature change. It is wired in the composition root in place of the
   bare provider, so every provider is instrumented identically.
2. **Delegate first, emit second, guard the emission.** `generate` calls the wrapped provider
   **first**, then computes a `Token_Count` and forwards exactly one emission to the
   `Usage_Sink` inside a `try/except` that swallows any exception — so a sink or store failure
   never changes the returned `GenerationResult`.
3. **Attribution without widening the contract.** `org_id`/`user_id` are read from the
   request-scoped tenancy context (`enterprise/tenancy`), not passed through `generate`, so the
   `LLM_Provider` surface stays unchanged.
4. **Keyless promise preserved.** The default `token_counter` is a pure function of the
   request/response text, the default sink writes to the in-memory `Usage_Store`, and the
   `Default_Cost_Model` uses its deterministic default rate — so wrapping the `Fallback_Provider`
   keeps every usage record reproducible with zero credentials.

_Validates: Requirements 12.1, 12.2, 12.3._

## How-to — How tenant isolation is enforced for observability resources at the data-access layer

Enforcement is structural and identical to Phase 5:

1. **`org_id` is a required store parameter.** Every `Usage_Store`, `Prompt_Store`, and
   `Evaluation_Store` method takes `org_id` and constrains its query with
   `WHERE org_id = :org_id` (descendants through their parent FK), so a cross-tenant row is
   never returned — the store yields `None`/`[]`.
2. **The router maps a miss to 404, never 403.** Handlers thread `principal.org_id` into the
   store; a `None`/empty result raises `AppError("not_found", 404)`, so cross-tenant existence
   is never leaked.
3. **The schema backs it up.** Every Phase 6 table carries
   `org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE`, so an org delete
   sweeps its observability state transitively and no orphaned cross-tenant row can survive.

Because the store is the enforcement point, a forgotten handler check can never leak another
tenant's usage, prompts, or evaluations.

_Validates: Requirement 12.4._

---

_Scope note:_ this record now covers Phases 1–6. The React frontend, third-party integrations
(Slack, Gmail, Drive, GitHub), and cloud deployment remain reserved for later phases and are
enabled — but not designed — by the modular seams established here.


---

# Phase 7 — React Web Frontend

This section records the rationale for the major architectural decisions in the Phase 7
**Web_Client** — a React + Vite + TypeScript single-page application in the `/frontend`
subdirectory that gives human Operators a browser console over the already-shipped
Phase 1–6 backend. It mirrors the Phase 7 design document so the reasoning is discoverable
from the repository itself.

## 39. UI-only — no backend capability or contract change

Phase 7 is deliberately **UI-only**: it consumes the stable, already-shipped HTTP/SSE
contracts and introduces no new backend capability and no backend contract change. Where a
desirable UI affordance has no shipped contract, the affordance is **omitted** rather than
met by a backend change. This one negative constraint governs the whole phase and keeps the
mature backend's semantics authoritative — the frontend mirrors auth, RBAC, tenancy, and
error semantics and never re-implements or relaxes them.

_Validates: Requirements 1.1, 1.6._

## 40. Types generated from the OpenAPI schema for contract fidelity

The typed API surface is **generated** from the backend's FastAPI OpenAPI schema
(`openapi-typescript` → `src/api/schema.d.ts`) and consumed through one tiny `openapi-fetch`
client (`src/api/client.ts`), the sole module every Backend_API call flows through. This
gives compile-time contract fidelity for a ~1 KB runtime and no generated imperative code in
the bundle. `tsc --noEmit` guarantees the client cannot reference an endpoint or field the
schema does not define, and a `codegen:check` step fails the build on drift between
`schema.d.ts` and `openapi.json`.

_Validates: Requirements 1.2, 1.3._

## 41. RBAC gating as a pure function that omits controls from the DOM

Control visibility is a **pure function** of the Session Role and the backend's static
role→permission map (`viewer ⊆ member ⊆ admin ⊆ owner`), mirrored exactly from
`enterprise/rbac.py` into `auth/rbac.ts`. The `Can` gate renders a control **iff**
`can(role, permission)`; when the permission is absent the control is **omitted from the
rendered DOM entirely**, not merely disabled — so the mirror can never grant more than the
backend authorizes, and the command palette never surfaces an action the Operator cannot
perform.

_Validates: Requirements 4.2, 4.3, 4.4, 4.5._

## 42. A single, total AppError → ClientError normalizer

Every non-2xx response and every network-layer failure flows through one **total**
normalizer, `mapError(status, body)`, producing a uniform `ClientError` that features render
via `ErrorBanner`/`ErrorSurface`. It never throws and always yields a non-empty,
user-presentable message: it copies `code`/`message`/`details` verbatim from a valid
envelope, maps `422` to per-field errors, yields `kind: "network"` for a transport failure
(surfaced as a connectivity error + `RetryNotice`), strips any stack text from `500`, and —
critically — presents a cross-tenant `404` as "not found" without referencing any other
organization. Forms keep input state independent of the request lifecycle so `429`, `502`,
and `guardrail_blocked` retries need no re-entry.

_Validates: Requirements 5.1, 5.2, 5.3, 5.5, 5.6, 4.7, 6.5._

## 43. 401 refresh-once-then-retry and cross-tenant 404-as-not-found

The API_Client auth middleware attaches `Authorization: Bearer <token>` to every
authenticated request (public auth endpoints exempt) and, on a `401` for an authenticated
request, calls `POST /auth/refresh` **exactly once**: on success it replaces the stored token
and retries the original request one time; on refresh failure or a second `401` it clears the
token and routes to `/login`. A per-original-request flag makes the policy provably
non-looping (at most one refresh, at most two attempts). Cross-tenant access is presented as
"not found", faithfully mirroring the backend's **404-never-403** existence-hiding rule.

_Validates: Requirements 3.3, 3.5, 3.6, 2.6, 4.7._

## 44. Fetch-based SSE with pure reducers and an exactly-one-terminal invariant

Both stream endpoints are **POST** returning `text/event-stream`, but the browser
`EventSource` API is GET-only — so the client streams via `fetch` + `ReadableStream`, splits
frames on the blank-line delimiter, and parses each with a pure `parseSseFrame`. Parsed
frames feed **pure `(state, event) → state` reducers**: the single-agent reducer keeps
non-terminal events in `sequence` order and closes on the first terminal (ignoring anything
after); the multi-agent reducer additionally buckets agent events by `role_id`, orders by
`sequence`, and records `approval_required` as a **non-terminal** pause. Making the
transport pure at its core lets the ordering and exactly-one-terminal guarantees be
property-tested with no live stream.

_Validates: Requirements 9.1, 9.2, 9.3, 10.2, 10.3, 10.5._

## 45. Verbatim cost rendering

Every cost the analytics dashboard displays — the top-level `total_cost` and each breakdown
entry's `total_cost` — is rendered as the **exact string** returned by the backend, with no
numeric parsing, rounding, or reformatting. The backend computes cost with `Decimal`; the
client treats the value as an opaque authoritative string (charts may position or label it,
but the string shown is verbatim), preventing any client-side rounding from misrepresenting
spend.

_Validates: Requirements 11.3, 11.4._

## 46. The premium UX stack (Tailwind + Radix + Framer Motion + cmdk + Monaco + react-markdown + Recharts)

The console targets a world-class SaaS bar, so the stack is deliberately additive and
well-established: **Tailwind** (utility velocity with a single tokenized source of truth
bound to CSS custom properties); **Radix UI** (accessible headless primitives — correct focus
trapping, ARIA, and keyboard behavior for free, styled via tokens); **Framer Motion**
(declarative 60fps transform/opacity animation with built-in reduced-motion support); **cmdk**
(a battle-tested, accessible ⌘K command menu); **Monaco** (full-featured prompt editing with
version diffing in the Prompt Studio); **react-markdown** + remark-gfm + rehype-sanitize
(safe, extensible markdown with code highlighting and inline citations); and **Recharts** for
analytics. Each is tree-shakeable, and the heavy ones (Monaco, charts) are code-split so the
initial bundle stays lean.

_Validates: Requirement 4.1 (and the Premium UX & Design System section)._

## 47. Keyless, deterministic testing via MSW + fast-check (Monaco/charts lazy + mocked)

The Web_Client mirrors the backend's keyless promise: the pure logic layer is unit- and
**property-tested** with `fast-check` (Properties 1–15, ≥100 iterations each) with no network
and no credentials, and every component/integration test runs against **MSW** mocks —
including simulated `text/event-stream` SSE and network failures — so the full suite needs no
live backend and no secrets. The heavy dependencies (Monaco, the charting library) are
dynamically imported and **mocked** with lightweight stubs under Vitest (never loaded in
tests), and Framer Motion runs with instant transitions so assertions never race animations.
A bundle-secret scan additionally asserts the production build embeds only the base URL /
non-secret config and no credential material.

_Validates: Requirements 1.5, and the keyless/deterministic testing strategy._

## How-to — Adding a new feature view without changing the backend

1. **Confirm a shipped contract exists.** The view may only bind to an endpoint already in
   the OpenAPI schema (`schema.d.ts`); if none exists, the capability is omitted (Decision 39).
2. **Call through the typed client.** Use `apiClient` (`api/client.ts`) via `runRequest`, so
   bearer attach, 401 refresh, and error normalization apply uniformly.
3. **Gate controls by permission.** Wrap any privileged control in `<Can permission=…>` so it
   is omitted from the DOM when the Session Role lacks it (Decision 41).
4. **Surface errors and empty/degraded states uniformly.** Render failures via
   `ErrorSurface`/`ErrorBanner` and zero-result/optional-off cases via `EmptyState`
   (Decision 42).
5. **Test keyless.** Add MSW-backed component tests and, for any new pure logic, a fast-check
   property test (Decision 47).


## Phase 7 status

**COMPLETE and in review on PR #14** (base `main`). The Web_Client ships **UI-only** over
the shipped Phase 1–6 HTTP/SSE contracts with **no backend capability or contract change**.
Verification: **168 keyless tests** (Vitest + React Testing Library over MSW, including
simulated `text/event-stream` SSE and network failures) and **15/15 correctness properties**
(fast-check, ≥100 iterations each) pass; `tsc --noEmit` contract-fidelity, `codegen:check`
schema-drift, and the `scan:bundle` no-secret checks all pass. Task 30 — the final manual
Phase Completion checkpoint — is intentionally **left for the user**.

# Phase 8 — Third-Party Integrations (Slack, Gmail, Google Drive, GitHub)

This section records the rationale for the Phase 8 `Integration_Layer` (Requirements 1–17
of the `agentforge-integrations` spec). Everything here **reuses, never reimplements** the
Phase 1–6 seams: the abstract `Tool_Interface` + `Tool_Registry` (`tools/base.py` /
`tools/registry.py`), the `Search_Provider` keyless/credentialed/mockable pattern, the
`Settings` + `load_settings` + `config/container.py` composition root, the uniform
`AppError` envelope (`api/errors.py`), the Phase 5 enterprise layer (`Principal`,
`get_current_principal` / `require_permission` / `get_org_id`, the static `RBAC_Policy`,
the request-scoped tenancy context, per-principal rate limiting, the 404-never-403
data-access rule, and the additive migration runner), and the Phase 6 observability layer
(the `Trace_Recorder` and the ordered `Guardrail_Pipeline`). The whole layer is fully
runnable and testable **keyless**: with zero integration credentials every integration is
Disabled, no outbound network call is ever made, and the entire property + unit suite runs
deterministically against mock connectors.

## 39. Each integration is an ordinary `Tool_Interface` behind the unchanged `Tool_Registry`

Slack, Gmail, Google Drive, and GitHub are each a concrete subclass of the existing
`Tool_Interface` — the same `name` / `description` / `input_schema` / `available` /
`invoke` contract the `RAG_Tool` and `Web_Search_Tool` implement. No new tool base class,
no parallel registry, and no separate `Tool_Result` type is introduced. The
`Agent_Orchestrator` and `Multi_Agent_Orchestrator` are **not modified**: they discover
every integration solely through the `Tool_Registry`, exactly as they discover the
built-in tools. This is the whole point of "interfaces at the seams" carried into Phase 8 —
adding four external services costs zero edits to the agent core.

_Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 17.3, 17.4._

## 40. A per-integration Connector transport seam mirroring `Search_Provider`

Each integration's real network work sits behind its own abstract `Connector` contract that
exposes an `available` flag plus exactly the operations its Tool invokes (Slack:
`read_channel` / `post_message`; Gmail: `search_messages` / `read_message` /
`send_message`; Google Drive: read-only `list_files` / `search_files` / `read_file`;
GitHub: `search_code` / `search_issues` / `read_repo` / `create_issue`). This is the direct
analogue of the Phase 3 `Search_Provider` (`available` + `search`), and each integration
ships the same trio:

- `Disabled_<Integration>_Connector` — the keyless default; `available == False`, performs
  no network call, and each operation raises defensively so an accidental call fails loudly
  rather than hitting the network (the Tool guards on `available` first, so it is never
  reached in normal operation).
- `Keyed_<Integration>_Connector` — constructed **only** when the Credential is present,
  built from the `SecretStr` plaintext obtained in the composition root, with a
  transport-level timeout.
- `Mock_<Integration>_Connector` — tests only; available, no network, returns injected
  canned data / raises injected failures, and spies on calls so "no network while Disabled"
  and "exactly one write call" are directly assertable.

The `Integration_Tool.available` property **mirrors its connector** exactly as
`Web_Search_Tool.available` mirrors `Search_Provider.available`, so a Disabled integration
is never offered to the agent by `Tool_Registry.list_specs()`.

_Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5._

## 41. Enablement is a pure function of Credential presence + Enable_Setting

Enablement is derived, never stored, mirroring the existing `Settings.active_search()`
helper:

```
Enabled(integration)  ⇔  Credential present  AND  Enable_Setting ≠ false
Disabled(integration) ⇔  Credential absent   OR   Enable_Setting = false
```

Credential presence and the non-secret `Enable_Setting` toggle are **separate** conditions:
a present Credential alone does not force enablement when the operator sets the toggle to
`false` (the same master-toggle discipline as Phase 6's `tracing_export_enabled`). The new
`Settings.integration_enabled(name)` helper returns this boolean and is the single source of
truth consumed by **both** the composition root's connector selection and the
`Integration_Status` service — so the two can never disagree. Because enablement is a pure
function of configuration, it is independent of any `Integration_Connection` persistence:
with no persistence configured the platform is fully functional and enablement is derived
solely from Credentials.

_Validates: Requirements 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 11.5._

## 42. The composition root is the only wiring seam (register-only-when-Enabled, startup-abort naming the integration)

`config/container.py` remains the single wiring seam and the only module that names concrete
Connectors. The existing `build_tool_registry` policy (register `RAG_Tool` always;
`Web_Search_Tool` only when keyed) is **extended** with "register each Integration_Tool only
when Enabled": `build_integration_tools` iterates the per-integration builders, selects the
`Disabled_` connector unless the integration is Enabled (then the `Keyed_` connector), and
yields a tool for registration only when `connector.available`. A Disabled integration is
therefore never registered, never listed, and holds no network path. If constructing or
registering an Enabled integration fails, `build_integration_tools` raises an
`AppError`-shaped error whose `details` name the offending integration and startup aborts —
the platform never starts in a partially registered state, matching the existing
`ConfigError`-aborts-startup discipline. A duplicate name surfaces the existing
`DuplicateToolNameError` unchanged.

_Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 2.6._

## 43. A fixed error-code vocabulary mapped onto `AppError`

Integration failures map onto a closed vocabulary carried in `Tool_Result.data["error_code"]`
inside a run and rendered through `AppError.code` on HTTP surfaces: `integration_disabled`,
`integration_unauthorized`, `integration_rate_limited`, `integration_upstream_error`,
`integration_timeout`. Connectors signal typed failures (`Unauthorized_Error` /
`Rate_Limited_Error` / `Upstream_Error` / other `ConnectorError`) that the base
`Integration_Tool` maps totally onto the vocabulary — the Tool never inspects
provider-specific error text. A Disabled invocation short-circuits to `integration_disabled`
with **no** connector call; exceeding the `Timeout_Budget` yields `integration_timeout`. The
mapping is two-layered: anticipated failures return `Tool_Result(ok=False)` (a normal,
non-raising return the `act` node records as a `tool_result` observation), while a genuinely
unexpected internal error still surfaces as `ToolError` and is contained by the `act` node —
so an integration failure never crashes a run.

_Validates: Requirements 6.1, 6.2, 7.1, 7.2, 7.3, 7.4, 7.5, 8.1, 8.2, 8.3, 8.4._

## 44. `SecretStr` redaction and no-secret persistence

Every integration Credential is an optional `SecretStr` on `Settings`, sourced only from the
environment and absent by default, so pydantic redacts it from `repr` / `str` /
`model_dump` / logs. The plaintext is obtained exactly once, in the composition root, to
build a `Keyed_` connector and is held only inside that connector — it is never placed into a
`Tool_Result`, the `Integration_Status` response, a surfaced error message, recorded/exported
trace data, or a persisted record. Surfaced messages are constructed from outcome fields and
fixed strings only, so neither a Credential value nor an internal stack trace ever reaches a
caller. The optional `Integration_Connection` persistence stores **non-secret** configuration
only (e.g. a default channel or repository); the `integration_connections` table has no
column for a token and structurally cannot hold credential material.

_Validates: Requirements 4.1, 4.2, 4.3, 4.4, 7.6, 9.2, 11.4, 16.2._

## 45. Tenant isolation at the data-access layer (404, never 403)

Consistent with Phases 5–6, tenancy for `Integration_Connection` records is enforced **at the
store, not the handler**. Every store method (`create` / `get` / `list_for_org`) takes
`org_id` as a required parameter and constrains its query with `WHERE org_id = :org_id`, so a
cross-tenant read/mutate matches zero rows → `None`/`[]` → `AppError("not_found", 404)`.
Cross-tenant access is **404, never 403**, because a 403 would leak the existence of a
resource in another org. Migration `0011_create_integration_connections.sql` is strictly
additive and idempotent (`CREATE ... IF NOT EXISTS`), carries
`org_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE`, and alters/drops no
pre-existing column, so an org delete sweeps its connection rows transitively. The
`InMemory_Integration_Connection_Store` is the keyless default; `Pg_Integration_Connection_Store`
is the production concrete behind the same seam.

_Validates: Requirements 11.1, 11.2, 11.3, 11.4._

## 46. Observability side-effects never change outcomes

Integration invocations are observable through the **existing** Phase 3/6 tracing seams — no
separate mechanism is introduced. The `Trace_Recorder` records the tool-call step scoped to
the acting `org_id`; no credential value ever enters recorded or exported data; and a failing
observability recording/export leaves the invocation outcome unchanged, reusing the Phase 6
suppression guarantee. Governance likewise reuses the enterprise seams unchanged: a Principal
lacking `run_agents` cannot initiate a run that could invoke an integration, declared write
actions (`slack.post_message`, `gmail.send_message`, `github.create_issue`) are gated behind
the same agent-run permission model with a security audit event recorded on denial, a
guardrail-blocked input invokes no integration, and per-principal rate limiting applies to
integration-driving requests.

_Validates: Requirements 8.x, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 16.1, 16.2, 16.3, 16.4._

## How-to — Adding a fifth integration (adapter + composition edit only)

Adding a fifth integration mirrors the Phase 3 "add a Tool" and Phase 6 "add a provider"
how-tos — no edit to the orchestrator, the `Tool_Registry`, or the `Tool_Interface`:

1. **Implement the Connector family + Tool** in a new module under `integrations/` (e.g.
   `integrations/jira.py`): a `Jira_Connector(Integration_Connector)` ABC exposing its
   operations, the `Disabled_Jira_Connector` (keyless default, `available == False`, no
   network), the `Keyed_Jira_Connector(token)` (built only with a non-empty token), and a
   `Mock_Jira_Connector` for tests; plus a `Jira_Tool(Integration_Tool)` subclass supplying
   `name` / `description` / `input_schema` and `_dispatch(arguments, connector)`. The base
   `Integration_Tool` provides the availability mirror, the Disabled short-circuit, the
   timeout wrapper, the failure-class → error-code mapping, result capping, and redaction for
   free.
2. **Add its `SecretStr` credential + enable-toggle to `Settings`** (`config/settings.py`) as
   optional / defaulted fields, and extend `integration_enabled(name)` coverage — mirroring
   the existing four; then list the new variables in `.env.example` with keyless-safe defaults.
3. **Register a connector builder in the composition root** (`config/container.py`): add a
   `build_jira_connector(settings)` returning the `Disabled_` connector unless
   `settings.integration_enabled("jira")` and append it to `_INTEGRATION_BUILDERS`.
   `build_integration_tools` and `build_tool_registry` pick it up automatically, and the
   property suite (parameterized over the integration set) covers the new integration with no
   test edit.

_Validates: Requirements 1.1, 2.1, 5.1, and the design's Extension note._

---

_Scope note:_ this record now covers Phases 1–6 and 8. Phase 8 ships the four pluggable tools,
the org-scoped `Integration_Status` introspection API, and the optional non-secret
`Integration_Connection` persistence; interactive OAuth UI flows, per-org secret vaulting, a
management frontend, streaming/webhook ingestion, and cloud deployment remain reserved for
later phases and are enabled — but not designed — by the modular seams established here.



---

# Phase 9 — Cloud Deployment & Production Infrastructure

This section records the rationale for the Phase 9 deployment infrastructure. Phase 9 is
**infrastructure only**: it adds Docker/Compose/nginx/CI artifacts and reuses, without
modifying, the existing application architecture — the `Settings` profile selection
(`local`/`production`), the `container.py` composition root, the additive startup
migration runner, the `AppError` envelope, organization tenancy, `/health/live` +
`/health/ready`, and the keyless-by-default deterministic test promise. The **single
app-adjacent edit** in the entire phase is the behavior-preserving `resolveConfig()`
runtime-config plumbing in `frontend/src/config.ts`. No API contract, business logic,
database-schema semantics, or observability behavior changes (Req 19), and `npm run
codegen:check` stands as the API-contract guardrail.

## 47. nginx as the single external entry point (routing + unbuffered SSE + security headers)

A single nginx reverse proxy is the sole published service and the single TLS termination
point; the frontend, backend, Postgres, and Redis stay on the internal Docker network with
no host ports. Path-based routing sends `/` to the SPA and the concrete backend prefixes
(+ SSE) to the API, forwarding request/response and event-stream bodies **byte-for-byte**
so the HTTP/SSE contract and the `AppError` envelope are preserved in transit. SSE
locations disable buffering/caching (`proxy_buffering off`, raised `proxy_read_timeout`,
`X-Accel-Buffering` honored) so streams are not held back. Hardened response security
headers (`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, a
tunable `Content-Security-Policy`) are additive metadata only and never alter bodies; HSTS
is emitted **only from the TLS/production server block**, never from plain HTTP.

_Validates: Requirements 6.1–6.5, 7.1, 7.4, 19.2._

## 48. Multi-stage, non-root images on non-privileged ports (8080/8443)

All three images (backend, frontend, proxy) are multi-stage and run **non-root**. The
backend builder installs runtime dependencies into a venv **before** copying `src/`, so a
source-only change reuses the cached dependency layer, and the slim runtime stage carries
only the venv + application under a dedicated `appuser` — no build toolchain or dev/test
tooling. The frontend and proxy use `nginxinc/nginx-unprivileged` (uid 101) listening on
**8080** (and **8443** for TLS); the runtime publishes host 80/443 to those ports, so no
container process binds a privileged port as root. `.dockerignore` files keep caches,
`.venv`, `.git`, `node_modules`, and local env files out of every build context.

_Validates: Requirements 1.1–1.6, 2.1–2.5, 3.1–3.3._

## 49. Runtime `config.js` for build-once / run-anywhere frontend

Vite bakes `VITE_API_BASE_URL` at build time, which would force a rebuild per environment.
Instead the Frontend_Image entrypoint renders a tiny `/config.js`
(`window.__AGENTFORGE_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" }`) at container start via
`envsubst`; `index.html` loads it before the app bundle, and `resolveConfig()` reads the
runtime value first, then the build-time value, then the documented default (preserved when
`API_BASE_URL` is unset). The same image serves byte-identical hashed assets everywhere and
differs only in `/config.js`, which carries the non-secret base URL only. This is the sole
app-adjacent edit and is pure config plumbing.

_Validates: Requirements 8.1–8.5, 19.1._

## 50. Unified keyless local compose + a production overlay (same images)

One base `docker-compose.yml` brings up the full platform **keyless** with a single
`docker compose up --build` (PROFILE=local, bundled non-secret DSNs, no credentials).
Production is expressed as an **overlay** (`docker-compose.production.yml`) applied on top
of the base so the service graph is defined once; the overlay only overrides profile,
injects secrets from a Secret_Source (no committed values, including `JWT_SECRET` and
non-default Postgres creds), adds `restart: unless-stopped`, enables the TLS block with
runtime-mounted certs, and pulls pinned GHCR images. `.env.production.example` enumerates
every production setting with placeholders only. `SecretStr` typing keeps credentials
redacted; no credential is ever baked into an image or committed.

_Validates: Requirements 4.1–4.6, 5.1–5.6, 7.2, 9.1–9.5, 10.1–10.5, 20.1–20.3._

## 51. On-startup migrations by default; optional one-shot for scale-out

The existing additive `run_migrations` runner keeps running in the `main.py` lifespan on
backend startup as the single-replica default — preserving One_Command_Startup with zero
new app code, halting on `MigrationError` and naming the failing id. For scale-out, the
production overlay adds an optional one-shot `migrate` service that runs the same runner
once and exits 0, with the backend gating on
`depends_on: migrate: condition: service_completed_successfully` so replicas never race
concurrent migrations. The runner stays additive and `schema_migrations`-tracked, so
re-runs and rollbacks to earlier images are safe.

_Validates: Requirements 12.1–12.4, 13.1–13.5, 18.3._

## 52. Four-job CI/CD → GHCR three-tag strategy; rollback via immutable tag

CI is four jobs chained with `needs:` — `test → build → publish → deploy` — so a red stage
stops all later stages. `test` runs both keyless lanes (backend `pytest -m 'not
integration' -q`, frontend `npm run ci`) plus the repo-wide secret scan with **no
credentials**; `build` builds all three images and runs the image-layer secret scan;
`publish` (guarded to `main`/`v*`) pushes to GHCR under a **three-tag** strategy — `latest`
(moving) + `<git-sha>` (immutable, every publish) + `<semver>` (only on a version tag);
`deploy` is gated on a manual-approval GitHub Environment and wraps the rollback-capable
`compose pull && up -d` shape. Rollback re-points `AGENTFORGE_IMAGE_TAG` to a prior
immutable tag and re-pulls; because migrations are additive, no DB rollback is needed.

_Validates: Requirements 14.1–14.4, 15.1–15.4, 18.1–18.2, 21.1–21.3._

## 53. Observability preserved — deployment never changes app behavior

Because the proxy forwards bodies and SSE byte-for-byte and no application source changes
beyond the runtime-config plumbing, all existing observability surfaces behave exactly as
before: the `Trace_Recorder` / `Tracing_Exporter` pipeline (NoOp in `local`, real exporter
when configured), the `/analytics` endpoints, and the guardrails subsystem are unchanged.
Traces, analytics, and guardrail decisions observed through the proxy are identical to
those observed hitting the backend directly.

_Validates: Requirements 19.1, 19.2, 19.4._

### Known deployment consideration (future work)

The backend image is **large** because it installs `torch` / `sentence-transformers` for
the default local embedding provider. Slimming it is **out of scope** for Phase 9; the
recommended future work is a **CPU-only `torch`** build (and/or making the local-embedding
dependency optional when a hosted embedding provider is used) to reduce image size and pull
time. This is a size/performance consideration only — it does not affect correctness or the
keyless promise.

---

_Scope note:_ this record now covers Phases 1–6, 8, and 9. Phase 9 ships the deployment and
production infrastructure (images, nginx proxy, compose files, CI/CD, docs) with no
application behavior or contract change; managed cloud services, Kubernetes/Helm,
DNS/domain registration, and real certificate issuance/renewal remain out of scope and are
handled externally.
