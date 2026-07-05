# AgentForge Web Frontend (Phase 7)

A React + Vite + TypeScript single-page application that gives human Operators a
browser console over the already-shipped AgentForge backend (Phases 1–6).

This phase is **UI-only**: the frontend consumes the stable, already-shipped
HTTP/SSE contracts and introduces **no new backend capability and no backend
contract change**. Where a UI need has no existing contract, the capability is
omitted rather than met by a backend change.

## Prerequisites

- **Node.js 22+** (see `engines` in `package.json`).
- A running AgentForge Backend_API to talk to (any environment that serves the
  Phase 1–6 contracts). No backend is required to run the test suite — it is
  fully mocked and keyless.

## Configuration (no secrets)

The only configuration the client reads is the **Backend_API base URL** (plus
non-secret feature flags). It is read exclusively from
`import.meta.env.VITE_API_BASE_URL`:

```bash
cp .env.example .env
# then edit .env:
VITE_API_BASE_URL=http://localhost:8000
```

No credential or secret value is ever read by the client or embedded in the
compiled bundle. The Operator obtains a JWT Access_Token **at runtime** via the
login flow; the token lives only in the browser session. The
[`scan:bundle`](#scripts) check enforces this by scanning the production build
for credential material.

## Install & scripts

```bash
npm install
```

<a id="scripts"></a>

| Script | Command | Purpose |
|---|---|---|
| `npm run dev` | `vite` | Start the dev server with HMR. |
| `npm run build` | `tsc --noEmit && vite build` | Type-check then produce the production bundle. |
| `npm run preview` | `vite preview` | Preview the production build locally. |
| `npm run test` | `vitest --run` | Run the full keyless test suite once (property + component/integration). |
| `npm run typecheck` | `tsc --noEmit` | Contract-fidelity type-check over `schema.d.ts` + every API call site. |
| `npm run codegen` | `openapi-typescript ./openapi.json --output ./src/api/schema.d.ts` | Regenerate the typed API surface from the backend OpenAPI schema. |
| `npm run codegen:check` | `node scripts/check-codegen.mjs` | Fail if `schema.d.ts` has drifted from `openapi.json`. |
| `npm run scan:bundle` | `node scripts/scan-bundle-secrets.mjs` | Scan the production build for credential material (must find none). |
| `npm run contract` | codegen-check + typecheck | Contract-fidelity gate. |
| `npm run ci` | codegen-check → typecheck → test → build → scan:bundle | The full local CI gate. |

## OpenAPI codegen step (contract fidelity)

The typed API client is **generated** from the backend's FastAPI OpenAPI schema
so the client can never drift from the shipped contracts:

1. The committed `openapi.json` is the input — it is dumped from the backend's
   `app.openapi()`. Regenerate it from the backend when contracts change.
2. `npm run codegen` runs `openapi-typescript` to emit `src/api/schema.d.ts`
   (a **generated** artifact — never hand-edited).
3. `src/api/client.ts` is a single `openapi-fetch` instance typed by
   `schema.d.ts`; it is the **sole** module through which every Backend_API call
   flows.
4. `npm run typecheck` (`tsc --noEmit`) then guarantees the client cannot
   reference an endpoint or field absent from the schema, and `npm run
   codegen:check` fails the build if `schema.d.ts` is out of sync with
   `openapi.json`. Both run in `npm run ci`.

## Design system

The console is built as a premium "AI Operating System" UI, not a generic admin
dashboard:

- **Theming & tokens** — dark-mode-first with a full light theme. All visual
  constants are **CSS custom-property design tokens** (semantic color roles,
  elevation, radius, blur, a 4px spacing scale, typography, and motion tokens)
  declared per theme in `src/styles/tokens.css` and consumed by Tailwind via its
  token-bound theme extension. A blocking pre-paint script in `index.html`
  applies `data-theme` before hydration to prevent a flash-of-wrong-theme.
- **Component library** — accessible primitives composed over **Radix UI**
  (shadcn/ui pattern) in `src/components/ui/`, styled purely through tokens, with
  glass surfaces reserved for overlay-class UI and a WCAG-AA solid fallback.
- **Command palette (⌘K / Ctrl-K)** — a `cmdk`-powered palette for navigation
  and actions; every entry is **RBAC-gated** by the same `can(role, permission)`
  used for nav, so it never surfaces an action the Operator cannot perform.
- **Keyboard shortcuts** — a central shortcut registry
  (`src/hooks/useKeyboardShortcuts.ts`) normalizes key-chords and surfaces
  collisions; a `?`-triggered overlay lists them grouped by area.
- **Motion, markdown & charts** — Framer Motion primitives that honor
  `prefers-reduced-motion`, a `react-markdown` renderer with inline citations and
  code highlighting, and lazy-loaded Monaco (Prompt Studio) and charts
  (analytics), all mocked in tests.

## Architecture & layering

The client mirrors the backend's clean layering, with a **pure logic layer**
isolated from I/O:

- **Pure logic layer** (no network, no credentials) — claims decode
  (`auth/token.ts`), the RBAC map + `can` (`auth/rbac.ts`), the AppError→
  ClientError normalizer (`api/errors.ts`), the SSE frame parser and single-/
  multi-agent reducers (`api/sse/*`), verbatim cost rendering, required-variable
  validation, design-token resolution, the shortcut-registry builder, and
  markdown citation extraction. These are unit- and **property-tested** with
  `fast-check`.
- **API_Client layer** — the single typed `openapi-fetch` client
  (`api/client.ts`) with auth middleware (bearer attach + 401
  refresh-once-then-retry) and the total error normalizer. It is the one place
  the concrete base URL and transport are named.
- **Feature views** (`src/features/*`) — declarative views mapped to the 15
  requirements (auth, org context + RBAC layout, org/API-key management, RAG
  query, documents, single-agent SSE run + trace, multi-agent SSE run +
  approval, analytics/usage, prompt registry, guardrails, evaluations,
  conversations). Server data is managed by TanStack Query keyed by
  `[resource, orgId, …]`; SSE runs use a `fetch`-based transport feeding the pure
  reducers.
- **Shared components** (`src/components/*`) — the `Can` RBAC gate (omits
  unauthorized controls from the DOM), `ErrorBanner`/`ErrorSurface`/`RetryNotice`
  for uniform error surfacing, and `EmptyState` for graceful degradation.

## Testing (keyless & deterministic)

The suite runs with no live backend and no credentials:

- **Vitest + React Testing Library** for component/interaction tests.
- **MSW** mocks the Backend_API — including simulated `text/event-stream` SSE and
  network failures — deterministically.
- **fast-check** property tests cover the pure logic layer (Properties 1–15,
  ≥100 iterations each).
- Heavy dependencies (Monaco, charts) are lazy-loaded and **mocked** in tests;
  Framer Motion runs with instant transitions so assertions never race
  animations.

Run everything with `npm run test`, or the full gate with `npm run ci`.
