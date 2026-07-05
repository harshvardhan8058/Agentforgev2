# Implementation Plan: AgentForge Phase 7 — React Web Frontend

## Overview

This plan converts the Phase 7 design into an ordered, incremental, test-driven coding
sequence for the **Web_Client** — a React + Vite + TypeScript single-page application in a
new `/frontend` subdirectory of the existing repository. The phase is **UI-only**: it
consumes the already-shipped Phase 1–6 HTTP/SSE contracts and introduces **no new backend
capability and no backend contract change**. Where a UI need has no existing contract, the
capability is omitted rather than met by a backend change (Req 1.6).

The build order follows the design's layering so no code is orphaned: first the project
scaffold + non-secret config + testing tooling, then the typed **API_Client** generated
from the backend OpenAPI schema, then the **pure logic layer** (claims decode, RBAC map,
error normalizer, SSE frame parser, single-agent + multi-agent reducers) — each with its
property test — then the auth middleware (bearer attach + 401 refresh-once-then-retry),
the `SessionProvider` + routing, the shared RBAC/error/empty-state components, then the
feature views mapped to all 15 requirements (auth, org context + RBAC layout, org
member/team management, API-key management, RAG query, documents, single-agent SSE run +
trace, multi-agent SSE run + approval, analytics/usage, prompt registry, guardrails,
evaluations, conversations), then the cross-cutting error-handling + graceful-degradation
wiring, the contract-fidelity checks, the documentation, and a final Phase Completion
checkpoint left for the user.

**Architecture consistency with Phases 1–6.** The Web_Client mirrors the backend's
conventions: a clean layering with a **pure logic layer** isolated from I/O (mirroring the
backend's pure/leaf seams), a single place where the concrete API base URL and transport
are named (`api/client.ts`, mirroring the composition root), RBAC gating as a pure function
of the Session Role and the backend role→permission map, and **keyless, deterministic
testing** — the pure logic layer is unit- and property-tested with no network and no
credentials, and all component/integration tests run against **MSW** mocks (including
simulated `text/event-stream` SSE and network failures) so the suite needs no live backend
and no secrets.

**Testing.** All 15 correctness properties from the design are implemented as **fast-check**
property tests (minimum 100 iterations each, one test per property, each tagged
`Feature: agentforge-frontend, Property {n}: {text}`), placed next to their implementation.
Example-based **Vitest + React Testing Library** component/integration tests (backed by
**MSW**) cover UI interactions, specific endpoint wiring, empty states, and degradation
scenarios. Contract-fidelity is enforced by a `tsc` type-check over the generated
`schema.d.ts` and a bundle scan asserting no secret material is embedded.

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Top-level tasks are never optional.
- Each task references the specific requirements (`_Requirements: X.Y_`) and the design
  section it implements (`_Design: <section>_`); property sub-tasks additionally reference
  the design property they validate.

## Tasks

- [x] 1. Scaffold the `/frontend` project (Vite + React + TS), non-secret config, and tooling
  - Create the `/frontend` subdirectory with a Vite + React 18 + TypeScript SPA:
    `index.html`, `package.json`, `vite.config.ts`, `tsconfig.json`, `src/main.tsx` (React
    root + providers), and `src/App.tsx` (layout shell + router mount) per the design's
    Module/Directory Layout.
  - Implement `src/config.ts` reading the Backend_API base URL **only** from
    `import.meta.env.VITE_API_BASE_URL` (plus non-secret flags); add a `.env.example` with
    the base-URL variable and no secret values, so the compiled bundle can never carry a
    credential.
  - Add the React Router v6 and TanStack Query v5 provider shell in `main.tsx` (router +
    query client), with no feature routes yet.
  - Configure the test toolchain: Vitest (`vitest --run`), React Testing Library,
    fast-check, and MSW; add npm scripts for `test`, `typecheck` (`tsc --noEmit`), and
    `build`.
  - _Requirements: 1.1, 1.4, 1.5_
  - _Design: Overview, Technology Choices, Module / Directory Layout, Testing Strategy (Tooling)_

  - [x]* 1.1 Write a smoke test for scaffold, config, and no-secret guarantee
    - Assert the app root renders; `config.ts` resolves the base URL from
      `import.meta.env.VITE_API_BASE_URL` and exposes no secret fields; and a scan of the
      built config module contains only the base URL / non-secret flags.
    - _Requirements: 1.1, 1.4, 1.5_

- [x] 2. Generate typed API types and build the openapi-fetch API_Client instance
  - Add `openapi-ts.config.ts` pointing at the Backend_API OpenAPI schema and an
    `openapi-typescript` codegen script that emits `src/api/schema.d.ts` (generated; not
    hand-edited).
  - Implement `src/api/client.ts`: a single `openapi-fetch` client bound to
    `config.baseUrl`, typed by `schema.d.ts`, as the sole module through which every
    Backend_API call flows (Req 1.2). No middleware yet (added in task 5).
  - Ensure any UI capability lacking a corresponding shipped contract is omitted — the
    client surface is exactly the generated schema (Req 1.6).
  - _Requirements: 1.2, 1.3, 1.6_
  - _Design: API_Client Layer, Data Models (generated schema), Technology Choices_

  - [x]* 2.1 Write a contract-fidelity type-check test for the generated client
    - Run `tsc --noEmit` over `schema.d.ts` + `client.ts` and assert the client cannot
      reference an endpoint or field absent from the schema; assert the codegen script
      regenerates `schema.d.ts` deterministically from the backend schema.
    - _Requirements: 1.2, 1.3_

- [x] 3. Implement the pure auth logic layer (`auth/token.ts`, `auth/rbac.ts`)
  - [x] 3.1 Implement `decodeClaims(token)` and `isExpired(claims, nowSeconds)` (`auth/token.ts`)
    - `decodeClaims` decodes a JWT payload and returns a `Claims` (`sub`, `org_id`, `role`,
      `exp`) for a well-formed token carrying all four correctly-typed claims, and returns
      `null` (never throws) for any malformed/undecodable token or any missing/mistyped
      claim; `isExpired` returns `true` iff `exp <= nowSeconds`.
    - _Requirements: 3.1, 3.2, 2.1, 2.3_
    - _Design: Pure logic modules (`auth/token.ts`)_

  - [x] 3.2 Implement `ROLE_PERMISSIONS` and `can(role, permission)` (`auth/rbac.ts`)
    - Mirror the backend `enterprise/rbac.py` map exactly: `viewer = {read}`,
      `member = viewer ∪ {run_agents, ingest_documents}`, `admin = member ∪ {manage_api_keys}`,
      `owner = admin ∪ {manage_members}`; `can` is a pure lookup.
    - _Requirements: 4.2, 4.3, 4.4, 4.5_
    - _Design: Pure logic modules (`auth/rbac.ts`)_

  - [x]* 3.3 Write property test for total, correct claims decoding
    - **Property 1: Claims decoding is total and correct**
    - **Validates: Requirements 3.1, 2.1, 2.3**
    - fast-check over arbitrary well-formed JWT payloads (all four claims) and arbitrary
      malformed/garbage tokens: assert never throws, returns the exact claims for
      well-formed input, and `null` for malformed/missing/mistyped input. Min 100 iterations.

  - [x]* 3.4 Write property test for expiry deciding authentication
    - **Property 2: Session expiry is decided solely by exp vs. now**
    - **Validates: Requirements 3.2**
    - fast-check over arbitrary `exp`/`nowSeconds` integers: assert
      `isExpired(claims, now) === (claims.exp <= now)`. Min 100 iterations.

  - [x]* 3.5 Write property test for the RBAC map nesting invariant
    - **Property 4: The client RBAC map mirrors the backend nesting invariant**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5**
    - fast-check over the four roles: assert `viewer ⊆ member ⊆ admin ⊆ owner` and every
      role contains `read`. Min 100 iterations.

- [x] 4. Implement the pure error and SSE logic layer (`api/errors.ts`, `api/sse/*`)
  - [x] 4.1 Implement the error-envelope normalizer `mapError(status, body)` (`api/errors.ts`)
    - Total function returning a defined `ClientError` (non-empty `message`, `kind`,
      `status`, `details`, optional `fieldErrors`) for any status (including `null` network
      failure) and any body (valid envelope, partial, garbage, none); copies `code`/
      `message`/`details` verbatim from a valid envelope; maps `422` to `fieldErrors`;
      yields `kind = "network"` for the null case; `500` yields the generic message with no
      stack text; a cross-tenant `404` message references no other organization.
    - _Requirements: 5.1, 5.2, 5.3, 5.5, 5.6, 4.7, 6.5, 8.5, 9.6, 10.7, 12.7, 14.5, 15.4_
    - _Design: Pure logic modules (`api/errors.ts`), Error Handling (Normalization, Status-specific behavior)_

  - [x] 4.2 Implement the SSE frame parser `parseSseFrame(raw)` (`api/sse/parse.ts`)
    - Pure parse of one `event: <type>\ndata: <json>\n\n` frame into `{ type, data }`
      (with the monotonic `sequence` inside `data`); returns `null` for an unparseable frame.
    - _Requirements: 9.1, 10.2_
    - _Design: Pure logic modules (`api/sse/parse.ts`), SSE Handling_

  - [x] 4.3 Implement the single-agent reducer (`api/sse/singleAgentReducer.ts`)
    - Pure `(state, event) -> state` fold keeping non-terminal `step`/`tool_call`/`delta`
      events in `sequence` order, transitioning to `closed` on the first terminal
      (`completion` → answer + citations + termination reason; `error` → error message),
      and ignoring events after a terminal.
    - _Requirements: 9.1, 9.2, 9.3_
    - _Design: SSE reducer interfaces (`singleAgentReducer`), SSE Handling_

  - [x] 4.4 Implement the multi-agent reducer (`api/sse/multiAgentReducer.ts`)
    - Pure fold exposing events ordered by `sequence`, bucketing agent events by `role_id`,
      recording `approval_required` as a **non-terminal** pause (`closed = false`, checkpoint
      exposed), and closing only on the single `completion` (final output + citations +
      termination reason) or `error` terminal.
    - _Requirements: 10.2, 10.3, 10.5_
    - _Design: SSE reducer interfaces (`multiAgentReducer`), SSE Handling_

  - [x]* 4.5 Write property test for total error-envelope normalization
    - **Property 5: Error-envelope normalization is total**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.5, 5.6, 4.7, 6.5, 8.5, 9.6, 10.7, 12.7, 14.5, 15.4**
    - fast-check over arbitrary status codes (and `null`) × arbitrary bodies (valid
      envelope, partial, garbage, none): assert never throws, always a non-empty message,
      verbatim `code`/`message`/`details` for valid envelopes, `fieldErrors` for `422`,
      `kind = "network"` for `null`, no stack text for `500`, and no cross-org leak for
      `404`. Min 100 iterations.

  - [x]* 4.6 Write property test for SSE frame round-trip
    - **Property 10: SSE frame parsing round-trips the backend frame format**
    - **Validates: Requirements 9.1, 10.2**
    - fast-check over arbitrary `{type, data-with-sequence}` pairs: rendering to
      `event: <type>\ndata: <json>\n\n` then `parseSseFrame` yields equal `type` and `data`.
      Min 100 iterations.

  - [x]* 4.7 Write property test for the single-agent reducer
    - **Property 8: The single-agent reducer preserves order and closes on exactly one terminal**
    - **Validates: Requirements 9.1, 9.2, 9.3**
    - fast-check over arbitrary finite event sequences ending in a terminal: assert order
      preserved, `closed` after first terminal with payload captured, post-terminal events
      ignored, exactly one terminal recorded. Min 100 iterations.

  - [x]* 4.8 Write property test for the multi-agent reducer
    - **Property 9: The multi-agent reducer orders by sequence, attributes roles, and treats approval as non-terminal**
    - **Validates: Requirements 10.2, 10.3, 10.5**
    - fast-check over arbitrary finite multi-agent event sequences: assert `sequence`
      ordering, `role_id` bucketing, `approval_required` leaves `closed = false` with the
      checkpoint exposed, and closes only on the single `completion`/`error`. Min 100 iterations.

- [x] 5. Implement the auth middleware and wire it into the API_Client (`api/auth-middleware.ts`)
  - [x] 5.1 Implement request-side bearer attachment
    - Attach `Authorization: Bearer <token>` on every authenticated request when a valid
      token is stored; exempt the public auth endpoints (`/auth/login`, `/auth/register-self`);
      attach nothing when no valid token is stored. Register the middleware on the
      `client.ts` instance.
    - _Requirements: 2.6_
    - _Design: API_Client Layer (auth-middleware request)_

  - [x] 5.2 Implement response-side 401 refresh-once-then-retry
    - On `401 unauthorized` for an authenticated request, call `POST /auth/refresh`
      **exactly once**; on success replace the stored token and retry the original request
      one time; on refresh failure or a second `401`, clear the token and route to `/login`.
      Use a per-original-request flag so the policy can never loop.
    - _Requirements: 3.3, 3.5, 3.6_
    - _Design: API_Client Layer (auth-middleware response), Error Handling (401 row)_

  - [x]* 5.3 Write property test for bearer attachment
    - **Property 7: Every authenticated request carries the bearer token**
    - **Validates: Requirements 2.6**
    - fast-check over arbitrary token/endpoint pairs: authenticated endpoints get exactly
      one `Authorization: Bearer <token>`; public auth endpoints never do; no token → no
      header. Min 100 iterations.

  - [x]* 5.4 Write property test for the bounded 401 refresh path
    - **Property 6: The 401 refresh path retries at most once**
    - **Validates: Requirements 3.3, 3.5, 3.6**
    - fast-check over arbitrary 401-then-{success|failure} response sequences (MSW-driven):
      assert at most one `POST /auth/refresh`, at most two original-request attempts, token
      replaced+retried on success, token cleared + `/login` route on failure. Min 100 iterations.

  - [x]* 5.5 Write an MSW integration test for the refresh flow end-to-end
    - Assert a live-style 401→refresh→retry→200 succeeds transparently and a
      401→refresh-401 clears the session and redirects to login.
    - _Requirements: 3.3, 3.5, 3.6_

- [x] 6. Implement the SessionProvider, useSession, and routing (`auth/`, `routing/`)
  - Implement `SessionProvider` + `useSession`: hydrate token from `localStorage`, decode
    claims via `decodeClaims`, validate expiry via `isExpired`, expose `orgId`/`role`/
    `isAuthenticated`/`login`/`logout`; `logout` clears the token and all derived state.
  - Implement `AppRouter` with public routes (`/login`, `/register`) and `ProtectedRoute`
    that redirects to `/login` whenever no valid Access_Token is stored (absent, expired,
    or malformed).
  - Wire the response-side 401/refresh-failure routing (task 5.2) to the router's `/login`
    redirect.
  - _Requirements: 3.1, 3.2, 3.4, 2.5, 2.1, 2.3_
  - _Design: Routing and Authenticated Layout, State Management Strategy (Session), Components and Interfaces (useSession)_

  - [x]* 6.1 Write component tests for session hydration and protected routing
    - Cover hydrate-valid-token → authenticated; expired/malformed token → `/login`;
      logout clears state and routes to `/login`; unauthenticated access to a protected
      route redirects to `/login`.
    - _Requirements: 3.1, 3.2, 3.4, 2.5_

- [x] 7. Implement the shared RBAC / error / empty-state components (`components/`)
  - [x] 7.1 Implement the `Can` RBAC gate (`components/Can.tsx`)
    - Render children **iff** `can(role, permission)` for the Session Role; otherwise render
      nothing so the gated control is absent from the DOM (not merely disabled).
    - _Requirements: 4.2, 4.3, 4.4, 4.5_
    - _Design: React component contracts (`Can`)_

  - [x] 7.2 Implement `OrgContextBadge`, `ErrorBanner`, `EmptyState`, and `RetryNotice`
    - `OrgContextBadge` renders the active Org_Context + Role (Req 4.1); `ErrorBanner`
      renders a normalized `ClientError` uniformly (message + relevant details, no stack);
      `EmptyState` renders explicit empty states; `RetryNotice` offers a retry affordance
      for connectivity errors.
    - _Requirements: 4.1, 5.1, 5.2, 5.5, 5.6, 6.2_
    - _Design: React component contracts, Error Handling, Graceful degradation_

  - [x]* 7.3 Write property test for the RBAC gate rendering
    - **Property 3: Control visibility is a pure function of role and required permission**
    - **Validates: Requirements 4.2, 4.3, 4.4, 4.5, 8.1, 12.4, 14.1**
    - fast-check over the four roles × five permissions rendering `<Can>`: assert the child
      is present in the DOM iff the backend map grants the permission, and absent (not
      disabled) otherwise. Min 100 iterations.

  - [x]* 7.4 Write component tests for the shared components
    - Cover `OrgContextBadge` showing Org_Context + Role; `ErrorBanner` rendering message +
      details with no stack for `500`; `EmptyState` and `RetryNotice` rendering.
    - _Requirements: 4.1, 5.1, 5.2, 5.5, 5.6_

- [x] 8. Checkpoint — pure logic layer and shared infrastructure
  - Ensure the pure-logic property suite (Properties 1, 2, 3, 4, 5, 6, 7, 8, 9, 10) plus the
    middleware/session/component tests are green against MSW with no network and no
    credentials, and `tsc --noEmit` passes. Ensure all tests pass, ask the user if questions
    arise.

- [ ] 9. Establish design tokens and theming (`styles/`, no-FOWT, `useTheme`)
  - Implement `styles/tokens.css`: dark-first + light **CSS custom properties** declared on
    `:root` / `[data-theme="dark"]` / `[data-theme="light"]`, covering the token families in
    the design — color **semantic roles** (`bg`, `surface`, `border`, `text`, `primary`,
    `accent`, `success`/`warning`/`danger`/`info`, `focus-ring`, agent-role accents),
    `elevation-0..4`, `radius-*`, `blur-*`, the 4px `space-*` scale, the typography scale,
    and motion tokens (durations + easings).
  - Implement `styles/theme.ts`: token TypeScript types (theme × semantic-role) plus the pure
    `resolveToken(theme, role)` helper that returns a defined, non-empty value for any
    declared role and a single deterministic fallback for any undeclared role (never throws).
  - Add `styles/tailwind.config.ts`: a Tailwind theme extension **bound to the CSS tokens** so
    utilities resolve to the custom properties (not hard-coded values); self-host
    **Inter/Geist** + **JetBrains Mono** as subset `woff2` with `font-display: swap`.
  - Add the **no-flash-of-wrong-theme** pre-paint inline script in `index.html` that resolves
    and applies `data-theme` on `<html>` before hydration, plus `providers/ThemeProvider.tsx`
    and `hooks/useTheme.ts` that read/set/persist the theme under the same `localStorage` key
    and honor `prefers-color-scheme`.
  - _Requirements: 4.1_
  - _Design: Premium UX & Design System §1 (design language & theming), §6 (Frontend Directory Layout — styles/, providers/, hooks/)_

  - [ ]* 9.1 Write property test for total design-token resolution
    - **Property 13: Design-token resolution is total over theme × semantic role**
    - **Validates: Premium UX & Design System §1; supports Requirements 4.1**
    - fast-check over `{ dark, light }` × arbitrary role identifiers (declared and undeclared):
      assert `resolveToken` never throws, returns a non-empty value for every declared role,
      and returns a single deterministic fallback for undeclared roles (stable across repeated
      calls). Min 100 iterations. Tag: `Feature: agentforge-frontend, Property 13: Design-token resolution is total over theme × semantic role`.

- [ ] 10. Build the design-system component library over Radix (`components/ui/`, `components/motion/`)
  - Implement `components/ui/` primitives styled purely via the design tokens over **Radix UI**
    (shadcn/ui composition pattern): `Button`, `Input`, `Dialog`, `Tabs`, `Tooltip`, `Toast`,
    `Skeleton`, `Badge`, `Card`, `DropdownMenu`, `Popover` — each accessible (focus trap, ARIA,
    keyboard) by inheriting Radix behavior, with per-primitive tree-shakeable imports.
  - Implement `components/motion/` **Framer Motion** primitives (`MotionFade`, `Stagger`,
    `StreamingCursor`) that are **reduced-motion aware** (honor `prefers-reduced-motion`) and
    **test-swappable** for a no-op/instant transition under Vitest.
  - Apply glass surfaces (backdrop-blur) only to overlay-class primitives (Dialog, Popover,
    Toast) with a solid-color WCAG-AA contrast fallback via `@supports not (backdrop-filter)`.
  - _Requirements: 4.1_
  - _Design: Premium UX & Design System §2 (component & styling stack), §4 (motion & performance)_

  - [ ]* 10.1 Write component/a11y tests for the UI and motion primitives
    - Cover: primitives render with token-driven classes; Dialog/Popover/DropdownMenu trap and
      restore focus and are keyboard-operable; motion primitives collapse to instant under a
      reduced-motion/test configuration; axe-core finds no violations on representative usage.
    - _Requirements: 4.1_

- [ ] 11. Wire providers, the ⌘K command palette, and the keyboard-shortcut system (`providers/`, `components/command/`, `hooks/`)
  - Mount `ThemeProvider`, `ToastProvider` (+ `hooks/useToast.ts` imperative API over Radix
    Toast), and `CommandPaletteProvider` in `main.tsx` above the router.
  - Implement `components/command/` **cmdk** palette (⌘K / Ctrl-K) for navigation and actions
    (new query, start run, new conversation, switch org, toggle theme, open shortcuts overlay);
    every command entry is **RBAC-gated** by the same `can(role, permission)` used for nav, so
    the palette never surfaces an action the Session Role cannot perform.
  - Implement `hooks/useKeyboardShortcuts.ts` with a **pure registry builder** that normalizes
    key-chords (case- and modifier-order-insensitive) and surfaces a collision when two actions
    declare the same normalized chord; add a `?`-triggered shortcuts overlay (Radix Dialog)
    listing chords grouped by area.
  - _Requirements: 4.2, 4.3, 4.4, 4.5_
  - _Design: Premium UX & Design System §3 (signature experiences — command palette, keyboard-shortcut system), §6_

  - [ ]* 11.1 Write property test for shortcut-registry uniqueness
    - **Property 14: The keyboard-shortcut registry has no duplicate binding collisions**
    - **Validates: Premium UX & Design System §3**
    - fast-check over arbitrary shortcut-declaration lists: assert normalization is
      case/modifier-order insensitive, every normalized chord maps to exactly one action, and
      any two actions sharing a normalized chord surface a collision (never silently
      overwrite/drop). Min 100 iterations. Tag: `Feature: agentforge-frontend, Property 14: The keyboard-shortcut registry has no duplicate binding collisions`.

  - [ ]* 11.2 Write component tests for the RBAC-gated palette (MSW)
    - Cover: ⌘K opens the palette; only commands permitted by `can(role, permission)` appear
      for a given Session Role; selecting a command navigates/acts; `?` opens the shortcuts
      overlay.
    - _Requirements: 4.2, 4.3, 4.4, 4.5_

- [ ] 12. Implement the markdown renderer with inline citations (`components/markdown/`)
  - Implement `components/markdown/` using **react-markdown** + **remark-gfm** +
    **rehype-sanitize** with on-demand code-block **syntax highlighting**, and a custom renderer
    that turns each inline `[n]` marker into a citation link to its source
    `{ document_id, chunk_id }`.
  - Implement the pure `extractCitations` helper: total (never throws) segmentation that maps
    every in-range `[n]` marker (`1..N`) to the matching `Citation` and renders any
    out-of-range / non-reference marker as inert text (no link, no dangling reference).
  - _Requirements: 7.2, 9.2_
  - _Design: Premium UX & Design System §3 (streaming chat inline citations), §2 (markdown stack)_

  - [ ]* 12.1 Write property test for citation extraction safety
    - **Property 15: Markdown citation extraction maps every marker to a valid citation or renders it inert**
    - **Validates: Premium UX & Design System §3; supports Requirements 7.2, 9.2**
    - fast-check over arbitrary markdown strings × citation lists of length `N`: assert
      `extractCitations` never throws, every in-range `[n]` becomes a link to the matching
      citation, every out-of-range/non-reference marker stays inert, no in-range marker is
      dropped, and no out-of-range marker becomes a link. Min 100 iterations. Tag:
      `Feature: agentforge-frontend, Property 15: Markdown citation extraction maps every marker to a valid citation or renders it inert`.

- [ ] 13. Build the responsive, RBAC-aware app shell
  - Implement the commercial-grade app shell: a **collapsible sidebar**, a **top bar**, the
    persistent `OrgContextBadge` (active Org_Context + Role), an **org switcher** for Operators
    holding tokens for multiple orgs, a **theme toggle**, logout, and an **RBAC-aware nav** whose
    entries are each wrapped in the `Can` gate so unauthorized destinations are absent from the DOM.
  - Implement responsive adaptation across the design breakpoints (`sm 640 · md 768 · lg 1024 ·
    xl 1280 · 2xl 1536`): `< md` collapses the sidebar into a slide-over **mobile drawer** (Radix
    Dialog) with the Org badge in the top bar; `md–xl` uses a persistent collapsible sidebar +
    content area; `≥ 2xl` honors reading max-width while dashboards use the extra width.
  - _Requirements: 4.1, 4.6_
  - _Design: Premium UX & Design System §1, §5 (accessibility & responsiveness); Routing and Authenticated Layout_

  - [ ]* 13.1 Write component tests for the responsive app shell
    - Cover: shell renders the Org badge + Role (4.1); nav entries appear only when `can()`
      grants them; the org switcher adopts the matching-`org_id` token (4.6); the theme toggle
      flips `data-theme`; `< md` renders the drawer while `md+` renders the persistent sidebar.
    - _Requirements: 4.1, 4.6_

- [ ] 14. Implement the auth feature views (`features/auth/`)
  - Implement `LoginView`: submit valid credentials → `POST /auth/login`, store token for
    the Session; on `401 auth_failed` show the envelope message and stay on login; block
    submission with empty email/password.
  - Implement `RegisterView`: submit self-registration → `POST /auth/register-self`, on
    `201` store the returned token; block submission with empty fields.
  - Wire the logout control to `useSession.logout` (clears token + derived state, routes to
    `/login`).
  - Premium UX (AI Operating System bar): deliver a refined, commercial-grade login/register
    experience, not a bare form —
    - A polished, centered auth layout with clear type hierarchy (display title, supporting
      copy, primary action) and generous layout rhythm; branded chrome that feels like a
      product, not a scaffold.
    - Use a glass (backdrop-blurred) overlay/card only where appropriate for the auth surface,
      with the solid-color WCAG-AA contrast fallback (`@supports not (backdrop-filter)`).
    - Rich state coverage: submit shows an in-button loading/spinner state (skeleton where a
      panel loads), an explicit success transition on authentication, and the uniform
      `ErrorBanner` for the `401 auth_failed` envelope while staying on login.
    - Surface transient outcomes via the toast/notification system (Radix Toast) without
      blocking, and support keyboard submit (Enter) with visible focus rings.
    - Fully accessible to WCAG 2.1 AA: labeled fields tied to validation messages, logical
      tab order, and icon-only controls carrying accessible names.
    - UI-only: binds to the existing `/auth/*` contracts (no backend contract change); motion
      honors `prefers-reduced-motion` and is instant under test.
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.4_
  - _Design: Routing and Authenticated Layout, Endpoint-to-view interface map (Auth)_
  - _Design: Premium UX & Design System §1 (design language & theming — glass, layout rhythm, typography), §3 (rich loading/empty/success/error states, premium auth + app shell), §5 (accessibility)_

  - [ ]* 14.1 Write component tests for auth flows (MSW)
    - Cover login stores token (2.1); `401 auth_failed` stays on login (2.2); register `201`
      stores token (2.3); empty-field blocking (2.4); logout clears + routes (3.4).
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.4_

- [ ] 15. Implement the org context, RBAC-aware layout, and org switcher (`features/`, layout)
  - Render the authenticated layout with the persistent `OrgContextBadge`, an RBAC-gated
    navigation menu (each entry wrapped in `Can`), and a logout control.
  - Implement the org switcher: selecting a different organization adopts the stored
    Access_Token whose `org_id` matches the selection as the active Org_Context, re-scoping
    all React Query cache keys (`[resource, orgId, ...]`) to re-fetch under the new context.
  - Ensure a resource `404 not_found` from cross-tenant access is presented as "not found"
    without indicating the resource exists in another org (via `mapError` + `ErrorBanner`).
  - _Requirements: 4.1, 4.6, 4.7_
  - _Design: Routing and Authenticated Layout, State Management Strategy (Server data), Error Handling (404 row)_

  - [ ]* 15.1 Write component tests for org context and switching
    - Cover badge shows Org_Context + Role (4.1); org switch adopts the matching token and
      re-scopes queries (4.6); cross-tenant `404` renders as not-found with no cross-org
      leak (4.7).
    - _Requirements: 4.1, 4.6, 4.7_

- [ ] 16. Implement org member/team management and API-key management (RBAC-gated, over `/orgs/*`)
  - Implement member/team management controls gated behind `manage_members` via `Can`,
    calling only the existing shipped `/orgs/*` contracts (list/add/update/remove members
    and teams as exposed by the backend); omit the controls entirely when the permission is
    absent.
  - Implement API-key management controls gated behind `manage_api_keys` via `Can`, calling
    only the existing shipped `/orgs/*` API-key contracts (list/create/revoke as exposed);
    omit entirely when the permission is absent.
  - Add no management capability that lacks a corresponding shipped backend contract (Req 1.6).
  - _Requirements: 4.4, 4.5, 1.6_
  - _Design: Routing and Authenticated Layout (Note on manage_members / manage_api_keys), React component contracts (`Can`)_

  - [ ]* 16.1 Write component tests for management gating
    - Cover: `manage_members` present → member/team controls in DOM and wired to `/orgs/*`;
      absent → controls omitted from DOM; `manage_api_keys` present → API-key controls in
      DOM and wired to `/orgs/*`; absent → omitted.
    - _Requirements: 4.4, 4.5_

- [ ] 17. Implement the RAG query view with citations (`features/query/`)
  - Implement `RagQueryView`: submit a non-empty query → `POST /query` with `top_k`, display
    the answer and `provider`; render each Citation's `document_id`/`chunk_id`; indicate
    ungrounded when `grounded` is false with empty citations; display guardrail `flags`;
    on `400 guardrail_blocked` show `details.reason` and withhold any answer. Gate the submit
    control behind `run_agents`.
  - Premium UX (AI Operating System bar): a live, ChatGPT/Perplexity-grade streaming answer
    experience —
    - Token-by-token streaming answer UI that renders `delta` output incrementally with a
      blinking **streaming cursor** from `components/motion/` (`StreamingCursor`), batching
      token appends within an animation frame for smoothness.
    - Rich **markdown + code blocks** via `components/markdown/` (react-markdown + remark-gfm
      + rehype-sanitize with on-demand syntax highlighting).
    - **Inline citations**: render each `[n]` marker as a link to its source
      `{ document_id, chunk_id }` using the pure `extractCitations` mapping (Property 15),
      leaving out-of-range/non-reference markers inert.
    - Full state coverage: **skeleton loaders** while awaiting the first tokens, an explicit
      **empty state** (illustration + CTA) before a query is run, a success rendering of
      answer + `provider` + grounded/ungrounded indicator + guardrail `flags`, and the uniform
      `ErrorBanner` for `guardrail_blocked` (answer withheld, `details.reason` shown).
    - A **command-palette entry** (⌘K) for "new query", RBAC-gated by `run_agents`.
    - Responsive from mobile → ultrawide; live region (`aria-live="polite"`) for streamed
      output; honors `prefers-reduced-motion` (cursor stops blinking) and is instant under test.
    - UI-only: binds to `POST /query` (no backend contract change).
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 4.2_
  - _Design: Endpoint-to-view interface map (Query), Error Handling (guardrail_blocked)_
  - _Design: Premium UX & Design System §3 (live streaming chat / inline citations, rich loading/empty/success/error states, command palette), §2 (markdown & motion stack), §4 (streaming smoothness), §5 (responsiveness & live regions); validates Property 15_

  - [ ]* 17.1 Write component tests for the query view (MSW)
    - Cover submit renders answer + provider (7.1, 7.6); citations render (7.2); ungrounded
      indicator (7.3); flags render (7.4); `guardrail_blocked` withholds answer + shows
      reason (7.5).
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_

- [ ] 18. Implement the documents view (`features/documents/`)
  - Implement `DocumentListView` + `UploadControl`: list `GET /documents` with filename,
    content type, size, status, chunk count, created-at; upload via `POST /documents`
    (multipart) showing `document_id`/`filename`/`chunk_count`/`status`; delete via
    `DELETE /documents/{id}` removing the row on `204`. Gate upload/delete behind
    `ingest_documents`; surface document error envelopes (413/415/400/422/500).
  - Premium UX (AI Operating System bar): a polished document-management surface, not a bare
    table —
    - **Premium upload**: drag-and-drop drop-zone with hover/active affordances plus a
      click-to-browse fallback, and a per-file **progress** indicator during `POST /documents`.
    - Document list with **skeleton loaders** during `isLoading` matching the final row/card
      layout, and a rich **empty state** (illustration + primary "upload" CTA) for zero
      documents.
    - **Optimistic delete**: remove the row immediately on `DELETE`, confirm via a toast
      (Radix Toast), and reconcile/rollback on error.
    - Responsive: metadata rows reflow into stacked **cards on mobile** (`< md`); tabular,
      token-spaced layout on larger breakpoints.
    - Uniform `ErrorBanner` for document error envelopes; visible focus rings and keyboard
      operability (WCAG AA).
    - UI-only: binds to the existing `/documents` contracts (no backend contract change);
      motion honors `prefers-reduced-motion` and is instant under test.
  - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 4.3_
  - _Design: Endpoint-to-view interface map (Documents), Error Handling (Document errors)_
  - _Design: Premium UX & Design System §3 (rich loading/empty/success/error states, toasts), §5 (responsiveness — cards on mobile), §1 (layout rhythm)_

  - [ ]* 18.1 Write component tests for the documents view (MSW)
    - Cover upload multipart + result fields (8.1, 8.2); list metadata rows (8.3); delete
      removes row on `204` (8.4); a document error status shows the envelope message (8.5).
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_

- [ ] 19. Implement the SSE transport hook and single-agent run + trace view (`api/sse/stream.ts`, `features/agent/`)
  - Implement `api/sse/stream.ts`: a `fetch` + `ReadableStream` SSE transport (POST,
    `Accept: text/event-stream`, bearer via the shared middleware) that splits frames on the
    blank-line delimiter, feeds `parseSseFrame`, and supports cancellation via
    `AbortController`; implement the `useSseRun` hook feeding frames into a pure reducer and
    exposing `{ state, isStreaming, cancel }`.
  - Implement `SingleAgentRunView`: streaming run via `POST /agent/stream` rendering events
    in order, final answer + citations on `completion`, error detail on `error`, and a
    cancel control while streaming; non-streaming run via `POST /agent/run` showing answer +
    `termination_reason` + citations. Gate run controls behind `run_agents`.
  - Implement `TraceView`: `GET /agent/runs/{id}/trace` rendering ordered entries; `404`
    presents the trace as not found.
  - Premium UX (AI Operating System bar): a live agent-run experience with an observability-grade
    trace —
    - **Live streaming run**: render `delta` output token-by-token with the `components/motion/`
      **streaming cursor**, incremental **markdown + code blocks**, and **inline citations**
      mapping each `[n]` to `{ document_id, chunk_id }` (`components/markdown/`, Property 15);
      a prominent cancel affordance while streaming.
    - **Trace timeline visualization** (`agent/TraceTimeline`): an ordered, zoomable timeline
      of trace entries showing step type, tool calls, and durations, using tokenized styling.
    - **Graceful degradation**: when tracing is configured **NoOp** and no exported detail
      exists, render the available streamed/persisted data and mark **"trace detail
      unavailable"** rather than showing an error (Req 6.3).
    - **Virtualization** (`@tanstack/react-virtual`) for long traces/event logs so thousands
      of streamed events stay smooth; memoize reducer-derived stream state to avoid re-render
      storms.
    - Skeleton loaders, empty/success/error states, live region for streamed output; run
      controls RBAC-gated by `run_agents`; responsive two-pane run/trace layout (`md–xl`).
    - UI-only: binds to `POST /agent/stream`, `POST /agent/run`, and `GET /agent/runs/{id}/trace`
      (no backend contract change); motion honors `prefers-reduced-motion` and is instant under test.
  - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
  - _Design: SSE Handling, Components and Interfaces (`useSseRun`), Endpoint-to-view interface map (Single-agent)_
  - _Design: Premium UX & Design System §3 (live streaming chat / inline citations, trace timeline visualization, graceful NoOp-trace degradation), §4 (virtualization, memoization, streaming smoothness), §2 (markdown & motion stack); validates Property 15_

  - [ ]* 19.1 Write component/integration tests for single-agent run + trace (MSW SSE)
    - Cover streamed events render in order + `completion` renders answer/citations (9.1,
      9.2); `error` terminal shows detail (9.3); non-streaming run fields (9.4); trace
      ordered by ordinal (9.5); trace `404` not-found (9.6); cancel aborts the stream (9.7).
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

- [ ] 20. Checkpoint — auth, layout, core feature views, and streaming transport
  - Ensure auth/org/query/documents/single-agent views and the SSE transport are green
    against MSW (including simulated `text/event-stream`), with the RBAC gate omitting
    unauthorized controls. Ensure all tests pass, ask the user if questions arise.

- [ ] 21. Implement the multi-agent run + approval view (`features/multiAgent/`)
  - Implement `MultiAgentRunView`: start via `POST /multi-agent/runs` showing `run_id`/
    `conversation_id`/`status`; open `POST /multi-agent/runs/{id}/stream` via `useSseRun`
    with the multi-agent reducer, attributing events to `role_id` and ordering by `sequence`;
    render the `ApprovalPanel` on `approval_required` with approve/reject/edit actions;
    submit decisions via `POST /multi-agent/runs/{id}/approval` showing `status` +
    `termination_reason`; render final output + citations on `completion`.
  - Implement the run result view: `GET /multi-agent/runs/{id}` showing `status`,
    `termination_reason`, final output, and the role-attributed ordered trace; `404` →
    not found; `409 run-not-awaiting-approval` → message + status refresh. Gate run/approval
    controls behind `run_agents`.
  - Premium UX (AI Operating System bar): a first-class, animated multi-agent workflow — the
    signature "AI Operating System" moment —
    - **Animated Planner → Researcher → Writer → Critic visualization**
      (`multiAgent/WorkflowVisualizer`): role nodes styled with **per-role accent tokens**
      (`role-planner`/`role-researcher`/`role-writer`/`role-critic`), and **live role
      transitions** (Framer Motion node/edge animation) as `agent_started`/`plan`/`research`/
      `draft`/`critic_feedback` events arrive.
    - **Per-role streaming panes** attributing events by `role_id` and ordered by `sequence`,
      each rendering incremental markdown/citations.
    - The **`approval_required` checkpoint rendered as a first-class, interactive, NON-terminal
      moment**: an **elevated approval panel** offering `approve` / `reject` / `edit`, visually
      distinct as a pause ("waiting on you", not finished), never conflated with a terminal
      completion.
    - **Reduced-motion fallback**: degrades to a static, ordered role layout under
      `prefers-reduced-motion` (and instant under test) without hiding any information.
    - Skeleton loaders, empty/success/error states; uniform `ErrorBanner` for `404`
      not-found and `409` (message + status refresh); virtualized long event logs; run/approval
      controls RBAC-gated by `run_agents`; responsive side-by-side panes at `≥ 2xl`.
    - UI-only: binds to the existing `/multi-agent/*` contracts (no backend contract change);
      preserves `approval_required` as non-terminal exactly as the multi-agent reducer defines.
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_
  - _Design: SSE Handling (multiAgentReducer), Endpoint-to-view interface map (Multi-agent), Error Handling (409 row)_
  - _Design: Premium UX & Design System §3 (animated multi-agent workflow visualization, approval checkpoint as first-class non-terminal moment), §1 (agent-role accent tokens), §4 (reduced-motion, virtualization, 60fps transforms/opacity), §5 (keyboard operability of the approval panel)_

  - [ ]* 21.1 Write component/integration tests for multi-agent run + approval (MSW SSE)
    - Cover start fields (10.1); role-attributed sequence-ordered events (10.2); approval
      checkpoint offers approve/reject/edit (10.3); approval submit + response (10.4);
      completion renders output + citations (10.5); run result + trace (10.6); `404`
      not-found (10.7); `409` message + status refresh (10.8).
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_

- [ ] 22. Implement the analytics / usage dashboard (`features/analytics/`)
  - Implement `UsageDashboardView`: `GET /analytics/usage` for the Org_Context showing
    `total_tokens` + `total_cost`; a start/end range control adding `start`/`end` query
    params; render `by_provider`/`by_model`/`by_user` breakdowns (key, tokens, cost); render
    every cost as the **exact** string from the backend (no reformatting); render an empty
    usage state for a no-record range; wrap each breakdown in its own error boundary so one
    failing breakdown is hidden while totals and other breakdowns still render. Gate behind
    `read`.
  - Premium UX (AI Operating System bar): beautiful, interactive observability dashboards on
    the Vercel/Retool bar —
    - **Lazy-loaded charts** (`analytics/UsageCharts` via **visx** or **Recharts**), code-split
      with `React.lazy` + `Suspense` (kept out of the initial bundle) and **mocked in tests**
      so the suite stays keyless, fast, and deterministic.
    - An interactive **time-range picker** adding `start`/`end` query params, with charts
      labeling/positioning `by_provider` / `by_model` / `by_user` breakdowns.
    - **Skeleton loaders** matching the final chart/tile layout during `isLoading`, and an
      explicit **empty usage state** for a no-record range.
    - **Per-breakdown error boundaries** so one failing breakdown is isolated while totals and
      the other breakdowns still render.
    - **Verbatim cost strings (Property 11)**: charts and tiles display each `total_cost`
      exactly as returned by the backend — never parsed, rounded, or reformatted (the chart
      may position/label the value, but the authoritative string shown is verbatim).
    - Tabular numerals for metrics; responsive — dashboards use the extra width at `≥ 2xl`;
      accessible chart semantics (WCAG AA).
    - UI-only: binds to `GET /analytics/usage` (no backend contract change).
  - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6_
  - _Design: Data Models (UsageReport), Graceful degradation (breakdown isolation)_
  - _Design: Premium UX & Design System §3 (analytics/observability dashboards, verbatim cost rendering), §2 (charts lazy-loaded & mocked), §4 (code-splitting/lazy-loading), §1 (tabular numerals), §5 (responsiveness); validates Property 11_

  - [ ]* 22.1 Write property test for verbatim cost rendering
    - **Property 11: Usage cost strings are rendered verbatim**
    - **Validates: Requirements 11.4, 11.3**
    - fast-check over arbitrary `UsageReport`s with arbitrary cost strings: assert every
      displayed cost (top-level + each breakdown entry) equals the exact backend string with
      no parsing/rounding/reformatting. Min 100 iterations.

  - [ ]* 22.2 Write component tests for the analytics dashboard (MSW)
    - Cover totals (11.1); range query params (11.2); breakdown rows (11.3); empty usage
      state (11.5); one breakdown failing is isolated while totals + others render (11.6).
    - _Requirements: 11.1, 11.2, 11.3, 11.5, 11.6_

- [ ] 23. Implement the prompt registry view (`features/prompts/`)
  - Implement `PromptRegistryView`: `GET /prompts` template names; `GET /prompts/{name}/versions`
    ascending versions; `GET /prompts/{name}?version=N` showing body/variables/created-at;
    `POST /prompts` (gated behind `ingest_documents`) appending a new version and showing the
    returned number.
  - Implement `RenderPromptForm`: block submission (no `POST /prompts/{name}/render`) iff any
    declared variable has no supplied value, prompting for exactly the missing set; on
    success display the rendered string; on `400 missing_variable` show `details.missing`.
  - Premium UX (AI Operating System bar): a **Prompt Studio** on the Anthropic Console bar,
    not a plain textarea —
    - **Monaco Editor** (`@monaco-editor/react`, `prompts/PromptStudio`) for editing prompt
      bodies, **lazy-loaded** via `React.lazy` + dynamic import and **mocked in tests** (never
      loaded under Vitest) so the suite stays keyless and deterministic.
    - **Version diffing** across immutable versions using Monaco `DiffEditor` for
      side-by-side comparison.
    - **Variable-aware editing** (highlighting declared variables) and a **render-preview
      panel** showing the rendered string.
    - **Required-variable validation (Property 12)**: block submission (no
      `POST /prompts/{name}/render`) iff at least one declared variable is unsupplied, prompting
      for exactly the missing set; `400 missing_variable` surfaces `details.missing` via
      `ErrorBanner`.
    - Skeleton loaders, empty/success states, monospace (JetBrains Mono) for bodies/JSON;
      version creation RBAC-gated by `ingest_documents`; responsive two-pane editor/preview.
    - UI-only: binds to the existing `/prompts/*` contracts (no backend contract change).
  - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6, 12.7_
  - _Design: Endpoint-to-view interface map (Prompts), Error Handling (missing_variable)_
  - _Design: Premium UX & Design System §3 (Prompt Studio — Monaco, version diffing, variable-aware editing, render preview), §2 (Monaco lazy-loaded & mocked), §1 (monospace typography); validates Property 12_

  - [ ]* 23.1 Write property test for required-variable render blocking
    - **Property 12: Required-variable validation blocks render on exactly the missing set**
    - **Validates: Requirements 12.6**
    - fast-check over arbitrary declared-variable sets × supplied subsets: assert submission
      is blocked (no request) iff at least one declared variable is unsupplied, and the
      prompted-for set equals exactly the missing declared variables. Min 100 iterations.

  - [ ]* 23.2 Write component tests for the prompt registry (MSW)
    - Cover list names (12.1); versions ascending (12.2); version detail (12.3); create
      version gated + returns number (12.4); render success (12.5); `400 missing_variable`
      shows missing names (12.7).
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.7_

- [ ] 24. Implement the guardrails and evaluations views (`features/guardrails/`, `features/evaluations/`)
  - Premium UX (AI Operating System bar): polished, insightful safety/quality views, not
    raw JSON dumps —
    - **Guardrails**: present the config as an **ordered card/list** of `name`/`kind` (in
      returned order) with tokenized styling, plus an **interactive evaluate panel** that
      visually distinguishes the `allow` / `flag` / `block` decision states (flag shows
      flags + reason; block shows reason); evaluate control RBAC-gated by `run_agents`.
    - **Evaluations**: insightful dataset/run views with **aggregate + per-item score
      visualization** (score tiles/bars using the lazy-loaded, test-mocked charting layer),
      dataset/run creation RBAC-gated by `run_agents`.
    - Full state coverage: **skeleton loaders** during `isLoading`, explicit **empty states**
      (no active guardrails; no datasets/runs), success confirmations via toast, and the
      uniform `ErrorBanner` for `404` not-found (no cross-org leak).
    - Responsive layouts; visible focus rings, keyboard operability, and WCAG AA contrast on
      the decision-state accents.
    - UI-only: binds to the existing `/guardrails/*` and `/evaluations/*` contracts (no
      backend contract change); motion honors `prefers-reduced-motion` and is instant under test.
  - _Design: Premium UX & Design System §3 (guardrails & evaluations views, rich loading/empty/success/error states), §1 (semantic decision-state color tokens), §2 (charts lazy-loaded & mocked), §5 (accessibility & responsiveness)_

  - [ ] 24.1 Implement `GuardrailsView`
    - `GET /guardrails/config` rendering each active guardrail's `name`/`kind` in returned
      order; `POST /guardrails/evaluate` (gated behind `run_agents`) showing the decision;
      `flag` shows flags + reason; `block` shows reason; empty config → explicit
      no-active-guardrails state.
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_
    - _Design: Endpoint-to-view interface map (Guardrails), Graceful degradation_

  - [ ] 24.2 Implement `EvaluationsView`
    - `POST /evaluations/datasets` (gated behind `run_agents`) showing `dataset_id`;
      `GET /evaluations/datasets` listing name + created-at; `POST /evaluations/runs` (gated
      behind `run_agents`) with `dataset_id` + evaluators showing aggregate + per-item
      scores; `GET /evaluations/runs/{id}` showing `aggregate_score` + per-item scores;
      `404` → not found.
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
    - _Design: Endpoint-to-view interface map (Evaluations), Error Handling (404 row)_

  - [ ]* 24.3 Write component tests for guardrails and evaluations (MSW)
    - Cover config order render (13.1); evaluate decision/flag/block (13.2–13.4); empty
      config state (13.5); create dataset (14.1); list datasets (14.2); run scores (14.3);
      run detail (14.4); cross-org `404` not-found (14.5).
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5, 14.1, 14.2, 14.3, 14.4, 14.5_

- [ ] 25. Implement the conversation context for runs (`features/conversations/`)
  - Implement `ConversationView` + a conversation-context hook: `POST /conversations`
    retaining the returned `conversation_id`; include the retained `conversation_id` in
    subsequent single-agent and multi-agent run requests; `GET /conversations/{id}`
    rendering messages ordered by position; `404` → not found. Wire the retained
    conversation id into the agent (task 19) and multi-agent (task 21) run submissions.
  - _Requirements: 15.1, 15.2, 15.3, 15.4_
  - _Design: Endpoint-to-view interface map (Conversations), Error Handling (404 row)_

  - [ ]* 25.1 Write component tests for conversation context (MSW)
    - Cover create + retain id (15.1); run request includes `conversation_id` (15.2);
      history ordered by position (15.3); `404` not-found (15.4).
    - _Requirements: 15.1, 15.2, 15.3, 15.4_

- [ ] 26. Wire cross-cutting error handling and graceful degradation
  - Ensure every feature surfaces failures through `mapError` → `ErrorBanner` with the
    status-specific behavior from the design: `422` field errors against form fields; `429`
    rate-limit notice preserving unsubmitted input; `500` generic message (no stack);
    `502 llm_provider_error` message preserving submitted input for retry; network failure →
    connectivity error + `RetryNotice`.
  - Ensure graceful degradation: explicit empty states for empty result sets; a NoOp-tracing
    run renders streamed/persisted data and marks trace detail unavailable; responses
    omitting optional capabilities render only what is present.
  - _Requirements: 5.3, 5.4, 5.5, 6.1, 6.2, 6.3, 6.4, 6.5_
  - _Design: Error Handling (Status-specific behavior, Input preservation), Graceful degradation_

  - [ ]* 26.1 Write component/integration tests for error handling and degradation (MSW)
    - Cover `422` field mapping (5.3); `429` notice + input preserved (5.4); `500` generic
      no-stack (5.5); `502` message + input preserved (6.5); network error + retry (5.6);
      empty states (6.2); NoOp trace unavailable (6.3); partial-capability rendering (6.4);
      optional-feature-disabled views still operate (6.1).
    - _Requirements: 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5_

- [ ] 27. Implement the contract-fidelity checks
  - Add a `tsc --noEmit` contract check over `schema.d.ts` + all API_Client call sites so
    the client cannot call an endpoint or read a field absent from the shipped OpenAPI
    schema; add the `openapi-typescript` codegen step to the CI/test scripts so drift from
    the shipped contracts is caught at build time.
  - Add a bundle scan asserting no secret material is present and only the base URL /
    non-secret config is embedded in the built output.
  - _Requirements: 1.2, 1.3, 1.5_
  - _Design: Testing Strategy (Contract-fidelity checks)_

  - [ ]* 27.1 Write the bundle-secret-scan test
    - Assert the production build embeds only the base URL / non-secret flags and contains
      no credential material.
    - _Requirements: 1.5_

- [ ] 28. Documentation — frontend README and Phase 7 ADR
  - Create `/frontend/README.md` covering: prerequisites, `VITE_API_BASE_URL` config (no
    secrets), install/dev/build/test scripts, the OpenAPI codegen step, and the pure-logic /
    feature-view layering.
  - Append a "Phase 7 — React Web Frontend" section to `docs/decisions.md` recording the key
    decisions: UI-only with no backend contract change; types generated from the OpenAPI
    schema for contract fidelity; RBAC gating as a pure function omitting controls from the
    DOM; the uniform `AppError` → `ClientError` normalizer; 401 refresh-once-then-retry and
    cross-tenant 404-as-not-found; fetch-based SSE with pure reducers and the
    exactly-one-terminal invariant; verbatim cost rendering; and keyless/deterministic
    testing via MSW + fast-check.
  - _Requirements: 1.1, 1.5, 1.6_
  - _Design: Overview, Design Goals, Error Handling, SSE Handling_

- [ ] 29. Checkpoint — features, degradation, contract checks, and docs
  - Ensure all feature views, cross-cutting error handling/degradation, contract-fidelity
    checks, and documentation are complete and the fast (property + component) suite is green
    against MSW. Ensure all tests pass, ask the user if questions arise.

- [ ] 30. Final Phase Completion checkpoint (leave unchecked for the user)
  - Run the full keyless frontend suite (`vitest --run`): all 15 fast-check property tests
    (Properties 1–15, ≥100 iterations each, each tagged
    `Feature: agentforge-frontend, Property N: ...`), all example-based component/integration
    tests (MSW, including simulated `text/event-stream` and network failures), the
    `tsc --noEmit` contract-fidelity type-check, and the bundle-secret scan. No live backend
    and no credentials are required.
  - Verify every correctness property (1–15) has a passing property test, every one of the
    15 requirements is covered by an implemented view/behavior, and no secret is present in
    the bundle. Report the pass/fail result.
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test sub-tasks and can be skipped for a faster MVP.
- Each task references specific acceptance criteria for traceability (`_Requirements: X.Y_`)
  and the design section it implements (`_Design: <section>_`); property sub-tasks
  additionally reference the design property they validate
  (`**Property N: <text>**` ; `**Validates: Requirements X.Y**`).
- The 15 fast-check property tests are the primary correctness surface for the pure logic
  layer (claims decode, RBAC map + gate, error normalizer, SSE parser + reducers, bearer
  attach, 401 refresh policy, verbatim cost, required-variable validation, plus the added
  design-token resolution, keyboard-shortcut-registry uniqueness, and markdown
  citation-extraction properties); example-based component/integration tests cover UI
  interactions, specific endpoint wiring, empty states, and degradation, per the design's
  Testing Strategy.
- The build is **UI-only**: no backend contract is added or changed. `manage_members` and
  `manage_api_keys` views/controls are included, gated over the existing `/orgs/*` contracts;
  any UI need without a shipped contract is omitted (Req 1.6).
- Everything is **keyless + deterministic**: the pure logic layer is tested with no network
  and no credentials, and all component/integration tests run against MSW mocks (including
  SSE and network failures) — no live backend and no secrets are ever required to run the
  full Phase 7 suite.
- Architecture mirrors Phases 1–6: a pure logic layer isolated from I/O, a single place
  (`api/client.ts`) where the concrete transport + base URL are named, and RBAC as a pure
  function of the Session Role and the backend role→permission map.

## Task Dependency Graph

```json
{
  "waves": [
    {
      "wave": 1,
      "tasks": ["1"],
      "description": "Scaffold /frontend (Vite + React + TS), non-secret config, and the Vitest/RTL/fast-check/MSW toolchain."
    },
    {
      "wave": 2,
      "tasks": ["2"],
      "description": "OpenAPI type generation (openapi-typescript) + the openapi-fetch API_Client instance."
    },
    {
      "wave": 3,
      "tasks": ["3", "4"],
      "description": "Pure logic layer: token/RBAC (Properties 1, 2, 4) and errors/SSE parser+reducers (Properties 5, 8, 9, 10) — disjoint modules, may run in parallel."
    },
    {
      "wave": 4,
      "tasks": ["5"],
      "description": "Auth middleware wired into the client: bearer attach (Property 7) + 401 refresh-once-then-retry (Property 6)."
    },
    {
      "wave": 5,
      "tasks": ["6", "7"],
      "description": "SessionProvider + routing and the shared RBAC/error/empty-state components (Property 3) — may run in parallel."
    },
    {
      "wave": 6,
      "tasks": ["8"],
      "description": "Checkpoint — pure logic layer + shared infrastructure green (Properties 1-10, session, middleware, components)."
    },
    {
      "wave": 7,
      "tasks": ["9"],
      "description": "Design tokens & theming (CSS custom properties, no-FOWT, useTheme) — the token foundation the UI library and app shell build on (Property 13)."
    },
    {
      "wave": 8,
      "tasks": ["10", "11", "12"],
      "description": "Design-system UI/motion library over Radix, providers + ⌘K command palette + keyboard-shortcut system (Property 14), and the markdown renderer with inline citations (Property 15) — all build on the design tokens + pure logic layer, may run in parallel."
    },
    {
      "wave": 9,
      "tasks": ["13"],
      "description": "Responsive, RBAC-aware app shell (sidebar/top bar/org badge/theme toggle) composing the UI library, command palette, and Can gate."
    },
    {
      "wave": 10,
      "tasks": ["14", "15", "16"],
      "description": "Auth views, org context + RBAC layout + org switcher, and member/team + API-key management (over /orgs/*) — distinct feature areas, may run in parallel."
    },
    {
      "wave": 11,
      "tasks": ["17", "18"],
      "description": "RAG query (streaming answer + inline citations, Property 15) and documents views — independent, may run in parallel."
    },
    {
      "wave": 12,
      "tasks": ["19"],
      "description": "SSE transport hook + single-agent run + trace timeline (feeds conversation wiring in task 25)."
    },
    {
      "wave": 13,
      "tasks": ["20"],
      "description": "Checkpoint — auth, layout, core feature views, and streaming transport green against MSW."
    },
    {
      "wave": 14,
      "tasks": ["21"],
      "description": "Multi-agent run + approval with animated workflow visualization (reuses the SSE transport + multi-agent reducer; feeds conversation wiring in task 25)."
    },
    {
      "wave": 15,
      "tasks": ["22", "23", "24"],
      "description": "Analytics/usage (Property 11), Prompt Studio/Monaco prompt registry (Property 12), and guardrails + evaluations — distinct feature dirs, may run in parallel."
    },
    {
      "wave": 16,
      "tasks": ["25"],
      "description": "Conversation context; wires conversation_id into the single-agent (19) and multi-agent (21) run submissions."
    },
    {
      "wave": 17,
      "tasks": ["26", "27", "28"],
      "description": "Cross-cutting error handling + graceful degradation, contract-fidelity checks, and documentation (README + Phase 7 ADR) — may run in parallel."
    },
    {
      "wave": 18,
      "tasks": ["29"],
      "description": "Checkpoint — features, degradation, contract checks, and docs green."
    },
    {
      "wave": 19,
      "tasks": ["30"],
      "description": "Final Phase Completion checkpoint (full keyless suite + all 15 property tests), left unchecked for the user."
    }
  ],
  "notes": [
    "Each wave depends on all prior waves; the generated schema and the pure logic layer precede all feature views.",
    "Wave 3 tasks 3 and 4 touch disjoint modules (auth/* vs api/errors + api/sse) and may run in parallel.",
    "Wave 5 tasks 6 and 7 (session/routing vs shared components) are independent given the pure logic layer.",
    "Design tokens & theming (task 9) precede the UI library (task 10), which is built purely over the tokens.",
    "The ⌘K command palette (task 11) and the app shell (task 13) depend on the pure logic layer + SessionProvider/Can (tasks 3, 6, 7) because command entries and nav are RBAC-gated by can(role, permission).",
    "Wave 8 tasks 10, 11, 12 touch distinct modules (components/ui + motion, providers + command, markdown) over the shared design tokens and may run in parallel.",
    "Wave 10 tasks 14, 15, 16 touch distinct feature areas and share only the layout shell and Can gate.",
    "Property 3 (RBAC gate) attaches to task 7 because the Can component renders the pure can() decision to the DOM.",
    "Properties 6 and 7 attach to task 5 because they concern the API_Client auth middleware.",
    "Property 13 (design-token resolution) attaches to task 9, Property 14 (shortcut-registry uniqueness) to task 11, and Property 15 (citation extraction) to task 12.",
    "Property 11 attaches to task 22 (verbatim cost rendering) and Property 12 to task 23 (required-variable render blocking).",
    "Task 25 depends on tasks 19 and 21 because the retained conversation_id is threaded into both run submissions.",
    "Optional (*) test sub-tasks may be deferred without blocking dependent waves.",
    "This phase is UI-only: no task adds or modifies a backend contract; management views are gated over existing /orgs/* contracts."
  ]
}
```
