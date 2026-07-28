# Dependency Security Maintenance

How to keep AgentForge's pinned dependencies free of known vulnerabilities, and why several
pins are deliberately security floors rather than mere compatibility bounds.

Every dependency in this project is **exactly pinned** (`pyproject.toml`, `package.json` +
`package-lock.json`). Exact pinning makes builds reproducible, but it also means a pin that
is never revisited silently ages into a known-vulnerable release. The checks below are the
counterweight; run them whenever you touch dependencies.

## Running the scans

```bash
# Backend — resolves the installed set against the PyPI advisory databases.
pip install -e ".[dev]"      # pip-audit is part of the dev extra
pip-audit

# Frontend — production dependencies only. This is the gate that must stay clean.
cd frontend && npm audit --omit=dev

# Frontend — including build-only tooling (see "Accepted findings").
cd frontend && npm audit
```

## Current status

| Scan | Status |
|---|---|
| `pip-audit` (backend) | 1 accepted finding (see below) |
| `npm audit --omit=dev` (frontend runtime) | **0 vulnerabilities** |
| `npm audit` (incl. build tooling) | 8 high, all build-only (see below) |

## Pins that are security floors

Do **not** lower these, and re-run `pip-audit` before raising the upper bounds. Each one sits
on a path that processes attacker-controlled input.

| Pin | Why it is a floor |
|---|---|
| `pyjwt` | Verifies Access_Tokens. Older releases had `crit` header bypasses and a verifier-side algorithm allow-list bypass — i.e. token forgery. |
| `python-multipart` | Parses multipart uploads. Older releases had a path traversal plus several parser DoS issues. |
| `starlette` (via `fastapi`) | Reconstructs `request.url` from the `Host` header and request path without validating them in older releases. |
| `pypdf` | Parses attacker-supplied PDFs during document ingest. |
| `markdown` | Parses attacker-supplied markdown during chunking. |
| `transformers` (in `constraints.txt`) | Loads model config/weights on the embedding path. **The old `<4.48` upper bound sat below the fix version for most published advisories**, so the image was pinned to a knowingly-vulnerable release. Keep the floor above the advisory line. |
| `torch` (in `Dockerfile`) | Loads the embedding model weights, so a `torch.load` deserialization RCE is directly on the ingest path. The previous `2.5.1` pin carried 22 advisories including GHSA-53q9-r3pm-6pq6. |

Note that `constraints.txt` and the `Dockerfile` torch pin are **separate** from
`pyproject.toml` and are not covered by a `pip-audit` run against your local virtualenv.
When bumping, check all three.

## Accepted findings

### `chromadb` — PYSEC-2026-311 (no upstream fix)

A pre-authentication code-injection issue in the ChromaDB **server**: an unauthenticated
request to `POST /api/v2/tenants/{tenant}/databases/{db}/collections` can pass a malicious
model repository with `trust_remote_code=true` and achieve RCE.

**Not reachable here.** `src/agentforge/vectorstore/chroma_store.py` uses
`chromadb.EphemeralClient()` — the embedded, in-process client. No Chroma HTTP server is
ever started and no `/api/v2/...` surface is exposed, so there is no endpoint for an attacker
to reach. There is no fixed release to upgrade to at time of writing.

**This acceptance is conditional.** It becomes invalid the moment anyone switches to
`chromadb.HttpClient` or runs `chroma run` as a service. If you make that change, this
advisory becomes live and must be re-evaluated. Prefer pgvector for any networked
deployment — `use_database=true` already selects it.

### Build-only: `js-yaml` and `brace-expansion`

Both are CPU-exhaustion DoS classes (quadratic parsing / unbounded expansion) reachable only
by feeding hostile input to a local `npm run codegen` or `npm run lint` invocation:

- `js-yaml` ← `openapi-typescript` → `@redocly/openapi-core`
- `brace-expansion` ← `minimatch` ← `eslint`, `eslint-plugin-jsx-a11y`

Neither ships in the browser bundle, so `npm audit --omit=dev` is clean and the deployed
artifacts are unaffected. Clearing them requires an `eslint` major-version bump, which also
moves the flat-config and plugin surface — deliberately left as separate work rather than
bundled into a security pass.

## When adding or bumping a dependency

1. Run the scans above; `npm audit --omit=dev` and `pip-audit` (modulo accepted findings)
   must be clean.
2. Prefer the advisory-clean version over the newest version if they differ.
3. If a finding cannot be fixed, document it under **Accepted findings** with an explicit
   reachability argument and the condition that would invalidate the acceptance — not just
   "low severity".
4. Re-run the full gates: `pytest -m 'not integration'`, `scripts/check_openapi.py`,
   `scripts/scan_secrets.py`, `cd frontend && npm run ci && npm run e2e`.
