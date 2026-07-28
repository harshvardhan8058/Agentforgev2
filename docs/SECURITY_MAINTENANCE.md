# Security Maintenance

How AgentForge tracks and resolves dependency advisories, and which residual
advisories are knowingly accepted (with the reasoning behind each decision).

## Standing rule

`npm audit fix --force` is **never** used. It silently performs breaking major
upgrades and downgrades. Advisories are resolved by an explicit, reviewed change:
a version bump, or a pinned `overrides` entry whose API compatibility has been
verified by running the full quality gate.

## Current posture

| Scope | Status |
| --- | --- |
| Frontend production dependencies (`npm audit --omit=dev`) | **0 vulnerabilities** |
| Frontend dev/build toolchain (`npm audit`) | 8 high — all from one accepted root (below) |

Verify at any time from `frontend/`:

```bash
npm audit --omit=dev   # must report 0 vulnerabilities
npm audit              # dev toolchain; see accepted advisory below
```

## Resolved advisories

### react-router — open redirect + SSR hydration injection (moderate)

`react-router` `6.0.0 – 7.17.0` carried an open-redirect issue reachable through
`<Link>` / `useNavigate`. No 7.x release clears both this and the later RSC-mode
CSRF advisory (`7.12.0 – 8.2.0`); only `react-router@8.3.0` clears both, and it
requires React `>= 19.2.7`.

Resolution: upgraded to **React 19 + react-router 8**. `react-router-dom` is no
longer published for v8, so all imports moved to `react-router` (a mechanical
change — the same symbols are re-exported). The `v7_startTransition` and
`v7_relativeSplatPath` future flags were removed because they are now default
behaviour.

### dompurify — mutation-XSS (moderate)

`monaco-editor` pins a vulnerable `3.2.x`. Overridden to a patched `3.4.x`, which
is API-compatible within the same major. Monaco is lazy-loaded and only used by
the Prompt Studio.

### js-yaml — quadratic CPU via YAML merge keys (high)

`@redocly/openapi-core` (transitively, via `openapi-typescript`) pins `4.2.0`.
Overridden to `^4.3.0`, the in-range patched release — no major bump required.

## Knowingly accepted advisory

### brace-expansion — DoS via pathological brace expansion (high, dev-only)

**Why it cannot be fixed.** Every `1.x` and `2.x` release falls inside the
vulnerable range (`<= 5.0.7`). The only patched line is `5.0.8`, whose CommonJS
build exports a *named* `{ expand }` instead of a callable default. ESLint's
transitive `minimatch@3.x` calls `require("brace-expansion")(...)`, so forcing
`5.0.8` breaks linting outright:

```
TypeError: expand is not a function
    at Minimatch.braceExpand (.../minimatch/minimatch.js:271:10)
```

This was verified empirically, and the override was reverted rather than shipped.

**Why the residual risk is acceptable.**

- It is a **dev/build-time dependency only** (ESLint and the OpenAPI codegen
  toolchain). It is never bundled — the production audit reports 0 vulnerabilities
  and `npm run scan:bundle` confirms nothing from this chain reaches `dist/`.
- The impact is denial of service through pathological glob patterns. The only
  globs expanded are the ones committed in `eslint.config.js` and our own npm
  scripts. They are never attacker-controlled, so there is no untrusted input path.
- Worst case is a slow or stalled lint job in CI, not a production or data risk.

**Exit condition.** Re-evaluate when ESLint's dependency chain moves to a
`minimatch` release that consumes `brace-expansion` via a named import, at which
point the `5.0.8+` override becomes safe. Re-test with `npx eslint .` before
adopting it.

## Backend

Python dependencies are pinned in `pyproject.toml` with `constraints.txt`
enforcing a CPU-only PyTorch build. Note that `constraints.txt` is what keeps the
backend image under its 4 GiB CI budget and CUDA-free — do not relax the torch
pin without re-checking the image-size gate in `.github/workflows/ci-cd.yml`.

`chromadb` carries a pre-authentication code-injection advisory with no patched
release. It is **not reachable** here: AgentForge uses the in-process
`EphemeralClient`, never the Chroma HTTP server the advisory targets. Anyone
switching to `HttpClient` must re-assess this.

## When adding or upgrading a dependency

1. Prefer the smallest bump that clears the advisory (patch < minor < major).
2. For a transitive pin, add an `overrides` entry and record the reasoning in
   `package.json` (`comment:overrides`) plus this document.
3. Run the full gate before committing — `npm run ci` (codegen check, lint,
   typecheck, 185 tests, production build, bundle-secret scan) and `npm run e2e`.
4. If a fix is impossible, document the reachability analysis and an exit
   condition here instead of silently suppressing it.
