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

---

_Scope note:_ this record covers Phases 1–3. Multi-agent orchestration, human-approval
workflows, enterprise auth/RBAC/multi-tenancy, cost/token analytics, the frontend,
third-party integrations, and cloud deployment are reserved for later phases and are
enabled — but not designed — by the modular seams established here.
