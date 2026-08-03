# AgentForge — Architecture Overview

> A visual, high-level tour of the v1.0 architecture. Diagrams are rendered with Mermaid. This document is descriptive of the merged `main` codebase; it does not change any behavior.

## 1. System context

```mermaid
flowchart TB
    user([Operator / User])
    subgraph edge[Public edge]
        nginx[nginx reverse proxy<br/>TLS, security headers, SSE-safe routing]
    end
    subgraph app[AgentForge platform]
        fe[Frontend SPA<br/>React + Vite]
        be[Backend API<br/>FastAPI]
    end
    subgraph data[Stateful services]
        pg[(PostgreSQL<br/>+ pgvector)]
        redis[(Redis<br/>rate limiting)]
    end
    subgraph optional[Optional external services]
        llm[LLM provider<br/>Groq]
        emb[Hosted embeddings]
        search[Web search]
        integ[Slack / Gmail / Drive / GitHub]
        trace[Trace export<br/>LangSmith / OTLP collector]
    end

    user --> nginx
    nginx --> fe
    nginx --> be
    be --> pg
    be --> redis
    be -.optional keys.-> llm
    be -.optional keys.-> emb
    be -.optional keys.-> search
    be -.optional keys.-> integ
    be -.optional keys.-> trace
```

Dashed edges are **optional** and inactive in keyless mode.

## 2. Deployment topology (docker compose)

```mermaid
flowchart LR
    subgraph compose[docker compose network]
        direction TB
        proxy[nginx<br/>:80/:443]
        frontend[frontend<br/>static build served by nginx]
        backend[backend<br/>uvicorn agentforge.main:app]
        migrate[[migrate<br/>one-shot migration runner]]
        postgres[(postgres)]
        redis[(redis)]
    end

    proxy --> frontend
    proxy --> backend
    backend --> postgres
    backend --> redis
    migrate --> postgres
    backend -. depends_on healthy .-> postgres
    backend -. depends_on healthy .-> redis
    proxy -. routes after healthy .-> backend
    proxy -. routes after healthy .-> frontend
```

- One command: `docker compose up --build` brings up the full stack, keyless, with migrations applied automatically (both on backend startup and via the one-shot `migrate` service).
- `docker-compose.production.yml` overlays secrets, TLS, and GHCR-published images without changing application code.

## 3. Backend composition root & context graph

The FastAPI `lifespan` builds nine object graphs once at startup via the single composition root `config/container.py`, and shares them on `app.state`. Tests pre-inject keyless in-memory doubles, which the lifespan respects.

```mermaid
flowchart TB
    settings[Settings<br/>load_settings]
    settings --> appctx[AppContext<br/>build_app_context<br/>LLM, embeddings, vector store, RAG services]
    appctx --> agentctx[AgentContext<br/>build_agent_context<br/>orchestrator, tools, memory, conversation, streaming, tracing]
    agentctx --> multictx[MultiAgentContext<br/>build_multi_agent_context<br/>roles, approval policy+gate, run store, streaming]
    settings --> entctx[EnterpriseContext<br/>build_enterprise_context<br/>auth, identity, RBAC, API keys, rate limiter]
    appctx --> obsctx[ObservabilityContext<br/>build_observability_context<br/>tracing exporter + trace export service, usage, cost, analytics, prompts, guardrails, evals]

    subgraph routers[Routers depend on app.state contexts]
        r1[query]
        r2[agent]
        r3[multi_agent]
        r4[auth / orgs]
        r5[analytics / prompts / guardrails / evaluations]
        r6[documents / ingest]
        r7[integrations]
        r8[conversations]
        r9[health]
    end

    appctx --> r1 & r6
    agentctx --> r2 & r8
    multictx --> r3
    entctx --> r4
    obsctx --> r5
    settings --> r7
```

Key principle: concrete implementations live only in `config/container.py`; every call site depends on an interface/seam, which is why keyless doubles can be swapped in transparently.

## 4. Request flow — RAG query

```mermaid
sequenceDiagram
    actor U as User
    participant N as nginx
    participant Q as /query router
    participant G as Guardrail pipeline
    participant R as Retrieval + vector store
    participant L as LLM provider (Instrumented)
    participant US as Usage store

    U->>N: POST /query {query, top_k}
    N->>Q: forward (bearer auth)
    Q->>G: pre-check input
    alt blocked
        G-->>U: AppError envelope (reason, withheld)
    else allowed
        Q->>R: retrieve top_k chunks (org-scoped)
        R-->>Q: chunks + citations
        Q->>L: generate(grounded prompt)
        L->>US: record usage/cost
        L-->>Q: answer (deterministic stub if keyless)
        Q->>G: post-check output (flags)
        Q-->>U: {answer, grounded, provider, citations[], flags[]}
    end
```

## 5. Streaming — single-agent SSE loop

```mermaid
sequenceDiagram
    actor U as User
    participant A as /agent/stream (SSE)
    participant O as Agent orchestrator (bounded)
    participant T as Tool registry (RAG / web)
    participant TR as Trace recorder
    participant X as Trace exporter (optional)

    U->>A: POST /agent/stream {task}
    loop bounded reason -> act -> observe
        A-->>U: event: step
        O->>T: tool_call
        A-->>U: event: tool_call
        T-->>O: observation
        O->>TR: record step
        A-->>U: event: delta (token)
    end
    A-->>U: event: completed {answer, citations, termination_reason}
    note over A,U: Exactly one terminal event (invariant)
    A->>TR: read the completed trace
    A->>X: export (best-effort, after the terminal event)
```

**Post-run trace export.** Every finished run is handed to the configured
`Tracing_Exporter` (NoOp / LangSmith / OTLP) through the `Trace_Export_Service`, which reads
the assembled trace back from the recorder — the same trace the API serves. The attachment
point differs per path, and the reason is always the same: the run must already be complete
and its result already delivered.

| Run path | How export attaches |
|---|---|
| `POST /agent/run`, `POST /multi-agent/runs`, terminating approval decision | FastAPI **background task** — runs after the response is sent |
| `POST /agent/stream` | the streaming service's **completion hook** — after the single terminal event |
| `POST /multi-agent/runs/{id}/stream` | after the service's frame iterator is exhausted |

Every failure is swallowed (a broken exporter, an unreachable collector, a failing trace
read), the export short-circuits before touching the trace store when it is off, and
`GET /observability/status` reports which destination — if any — is active.

## 6. Multi-agent supervisor with human approval

```mermaid
stateDiagram-v2
    [*] --> Planner
    Planner --> Researcher
    Researcher --> Writer
    Writer --> Critic
    Critic --> ApprovalRequired: revisions within bound
    ApprovalRequired --> Writer: reject / edit
    ApprovalRequired --> Completed: approve
    Critic --> Completed: auto (keyless / auto policy)
    Completed --> [*]
    note right of ApprovalRequired
        approval_required is non-terminal
        POST /multi-agent/runs/{id}/approval
        409 if not awaiting approval
    end note
```

## 7. Data model & migrations

Seventeen additive SQL migrations, one per phase area, applied in order on startup (halting and naming the failing id on error):

```mermaid
flowchart LR
    m1[0001 pgvector] --> m2[0002 core tables] --> m3[0003 conversations]
    m3 --> m4[0004 agent traces] --> m5[0005 multi-agent runs]
    m5 --> m6[0006 enterprise identity] --> m7[0007 org_id tenancy]
    m7 --> m8[0008 usage records] --> m9[0009 prompt registry]
    m9 --> m10[0010 evaluations] --> m11[0011 integration connections]
    m11 --> m12[0012 document content hash] --> m13[0013 audit events]
    m13 --> m14[0014 spend budgets] --> m15[0015 webhooks]
    m15 --> m16[0016 budget notifications] --> m17[0017 webhook outbox]
```

All resources are `org_id`-scoped; cross-tenant access resolves to 404, never 403. Two tables
carry deliberate non-cascade rules: `usage_records.user_id` and `audit_events.actor_user_id`
are `ON DELETE SET NULL`, so deleting a user cannot erase the cost it incurred or the record
of what it did.

`budget_notifications` (0016) is the one table whose **primary key is a claim** rather than an
identity: `(org_id, period_start, threshold_percent)` plus `INSERT … ON CONFLICT DO NOTHING` is
how two concurrent requests observing the same budget crossing produce exactly one notification.

## 7a. Notification flow (webhooks)

The platform could observe everything and tell nobody until 0015. One seam now serves runs,
ingestion, guardrails and spend:

```mermaid
flowchart LR
    subgraph request[Request path]
        run[run / ingest / query]
        guard[input guardrail]
        budget[budget enforcement]
    end
    subgraph after[After the response]
        bg[BackgroundTasks]
        deferred[deferred-work seam<br/>api/errors.py]
        pool[alert service pool]
    end
    dispatcher[Webhook_Dispatcher<br/>who: one row per subscription]
    outbox[(webhook_outbox<br/>when: durable schedule)]
    worker[Webhook_Delivery_Worker<br/>leases a batch, one attempt each]
    emitter[Webhook_Emitter<br/>how: render, sign, one attempt]
    admission[URL admission<br/>re-checked per attempt]
    endpointx[(tenant endpoint)]
    log[(webhook_deliveries)]

    run -->|success| bg --> dispatcher
    guard -->|400 raised| deferred --> dispatcher
    budget -->|threshold crossed| pool --> dispatcher
    dispatcher --> outbox
    worker -->|claim due| outbox
    worker --> emitter --> admission --> endpointx
    emitter --> log
```

The split across dispatcher / outbox / worker is what makes the guarantees available. Enqueueing is
bounded work whose cost does not depend on a consumer, so it is safe while a caller waits;
delivering is unbounded work that depends entirely on a consumer, so it must not be. Retry state
lives in the table rather than in a process, which is what survives a deploy.

Three scheduling mechanisms feed the dispatcher, each for a reason. Successful runs use FastAPI's
`BackgroundTasks`. A *refusal* is raised rather than returned, so it has no response to hang work
on — hence the deferred-work seam in `api/errors.py`. Budget notifications use the alert service's
own pool, so a claim round trip never lands on the request path.

Three scheduling mechanisms, each for a reason. Successful runs use FastAPI's `BackgroundTasks`.
A *refusal* is raised rather than returned, so it has no response to hang work on — hence the
deferred-work seam in `api/errors.py`, which attaches the task to the error response the
exception handler builds. Budget notifications use the alert service's own pool, so they neither
queue ahead of a run's own post-response work nor hold a streamed connection open.

## 8. CI/CD pipeline

```mermaid
flowchart LR
    test[test<br/>keyless pytest + frontend ci] --> build[build<br/>backend / frontend / proxy images]
    build --> publish[publish<br/>tag: latest + git SHA + semver]
    publish --> deploy[deploy<br/>production, gated]
```

- Four independent jobs with dependencies; `deploy` and `publish` are skipped on PRs.
- Images tagged with `latest`, the git SHA, and a semantic version when available, enabling immediate rollback by pinning a prior tag.

## Architectural invariants (enforced across the codebase)

1. **Keyless-by-default** — full boot and demo with zero credentials.
2. **Single composition root** — concretes only in `config/container.py`.
3. **Tenancy** — `org_id` scoping; cross-tenant → 404.
4. **Secrets** — typed `SecretStr`, never logged.
5. **Uniform errors** — `AppError { error: {code, message, details} }`.
6. **Additive migrations** — never rewrite existing ones.
7. **Governance side channels never fail the work they govern** — trace export runs after the
   response, an audit write is fail-open by default (fail-closed reports `503
   audit_unavailable` on an *applied* change rather than pretending to roll it back), and a
   spend check that cannot compute spend allows the run.
7. **Streaming invariant** — exactly one terminal SSE event per run.
