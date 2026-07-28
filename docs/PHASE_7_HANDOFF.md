# Phase 7 Handoff — React Web Frontend

Tight, skimmable handoff for future sessions. Phase 7 is **COMPLETE and in review** on
**PR #14** (base `main`). It is **UI-only**: it consumes the shipped Phase 1–6 HTTP/SSE
contracts and changes **no backend behavior or contract**.

## What shipped

A React 19 + Vite + TypeScript operator console in [`/frontend`](../frontend), mirroring
the backend's clean layering with a **pure logic layer** isolated from I/O.

**Architecture**
- **Pure logic layer** (no network, no credentials): claims decode (`auth/token.ts`),
  RBAC map + `can` (`auth/rbac.ts`), `AppError → ClientError` normalizer (`api/errors.ts`),
  SSE frame parser + single/multi-agent reducers (`api/sse/*`), verbatim cost rendering,
  required-variable validation, design-token resolution (`styles/theme.ts`), shortcut
  registry (`hooks/useKeyboardShortcuts.ts`), markdown citation extraction
  (`components/markdown/extractCitations.ts`).
- **API_Client layer**: one typed `openapi-fetch` client (`api/client.ts`) — the sole place
  the base URL and transport are named — with auth middleware (bearer attach + 401
  refresh-once-then-retry) and the total error normalizer.
- **Feature views** (`src/features/*`) mapped to the 15 requirements; server data via
  TanStack Query keyed by `[resource, orgId, …]`; SSE runs via a fetch-based transport
  feeding the pure reducers.
- **Design system**: Tailwind (token-bound) + Radix + Framer Motion + cmdk (⌘K palette) +
  Monaco (Prompt Studio) + react-markdown + Recharts/visx.

**Feature map**: auth (login/register/logout) · org context + RBAC layout + org switcher ·
org member/team + API-key management (over `/orgs/*`) · RAG query with inline citations ·
documents (upload/list/delete) · single-agent run (streaming + non-streaming) + trace ·
multi-agent run + approval (animated Planner→Researcher→Writer→Critic) · analytics/usage ·
prompt registry (Prompt Studio + version diffing) · guardrails · evaluations ·
conversations.

## The 15 correctness properties (fast-check, ≥100 iterations each)

| # | Property | Test location (`frontend/src/`) |
|---|---|---|
| 1 | Claims decoding is total and correct | `auth/token.test.ts` |
| 2 | Session expiry decided solely by `exp` vs. now | `auth/token.test.ts` |
| 3 | Control visibility is a pure function of role × permission | `components/Can.test.tsx` |
| 4 | Client RBAC map mirrors backend nesting invariant | `auth/rbac.test.ts` |
| 5 | Error-envelope normalization is total | `api/errors.test.ts` |
| 6 | 401 refresh path retries at most once | `api/auth-middleware.test.ts` |
| 7 | Every authenticated request carries the bearer token | `api/auth-middleware.test.ts` |
| 8 | Single-agent reducer preserves order, one terminal | `api/sse/singleAgentReducer.test.ts` |
| 9 | Multi-agent reducer orders by sequence, attributes roles, approval non-terminal | `api/sse/multiAgentReducer.test.ts` |
| 10 | SSE frame parsing round-trips the backend format | `api/sse/parse.test.ts` |
| 11 | Usage cost strings rendered verbatim | `features/analytics/verbatimCost.property.test.tsx` |
| 12 | Required-variable validation blocks render on exactly the missing set | `features/prompts/requiredVariables.property.test.ts` |
| 13 | Design-token resolution total over theme × role | `styles/theme.test.ts` |
| 14 | Keyboard-shortcut registry has no duplicate collisions | `hooks/useKeyboardShortcuts.test.ts` |
| 15 | Markdown citation extraction maps every marker to a valid citation or renders it inert | `components/markdown/extractCitations.test.ts` |

## How to run / verify

```bash
cd frontend
npm install
npm run ci   # codegen:check -> typecheck -> test -> build -> scan:bundle
```

Latest run: **168 tests passing** across 37 files, **15/15 properties**, bundle-secret scan
clean, production build succeeds. Individual stages: `npm run codegen:check`,
`npm run typecheck`, `npm run test` (vitest `--run`), `npm run build`, `npm run scan:bundle`.

## Keyless / deterministic testing approach

- **MSW** mocks the entire Backend_API, including simulated `text/event-stream` SSE and
  network failures — no live backend, no credentials.
- **fast-check** covers the pure logic layer (the 15 properties above).
- **Monaco and charts are lazy-loaded and mocked** under Vitest (never loaded in tests);
  Framer Motion runs with instant transitions so assertions never race animations.
- A **bundle-secret scan** asserts the production build embeds only the base URL /
  non-secret config.

## Branch / PR state (+ merged-stack correction)

- Branch `feat/agentforge-frontend`, PR **#14** (base `main`), open / in review.
- **Correction:** the Phase 3–6 PR stack is **already merged to `main`** (`main` was at
  **cfd8204**, "Merge pull request #12 … feat/agentforge-enterprise"). The
  `feat/agentforge-observability` branch was **not on the remote**, so the frontend branch
  is based directly off `main`. Do **not** assume or rebase onto the old unmerged stack.

## UI-only constraint

Every affordance binds to an already-shipped contract in `openapi.json` / `schema.d.ts`.
Where no contract exists, the capability is **omitted** rather than met by a backend change.
RBAC, tenancy, and error semantics are mirrored from the backend, never relaxed.

## Known non-blockers

- **Main bundle > 500 kB advisory**: Vite warns the initial chunk exceeds 500 kB. This is an
  advisory only — the heavy dependencies (**Monaco** → `PromptStudio` chunk, **charts** →
  `UsageCharts` chunk) are **already code-split** and lazy-loaded, so they are not in the
  initial critical path. Optional future polish: `manualChunks` tuning.
- **Backend `openapi.json` regeneration**: the committed `frontend/openapi.json` is dumped
  from the backend's `app.openapi()`. When backend contracts change, regenerate it, then run
  `npm run codegen` (emits `src/api/schema.d.ts`); `npm run codegen:check` fails the build on
  drift.
- **Task 30** (final manual Phase Completion checkpoint) is intentionally left unchecked for
  the user.

## Recommended next step

**Phase 8 — Third-party Integrations (Slack / Gmail / Drive / GitHub)**, **pending explicit
user approval**. Do not auto-start. Phase 9 (Cloud Deployment) follows.
