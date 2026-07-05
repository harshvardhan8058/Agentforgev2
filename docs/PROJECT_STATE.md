---
current_phase: "Phase 6 — Production Observability (COMPLETE, in review)"
current_branch: feat/agentforge-observability
current_commit: cbf449b733c742262dd77d8376ff086ca2a6f21f  # short cbf449b
current_pr: 11  # base feat/agentforge-enterprise
architecture_version: "6.0 (observability layer added)"
current_api_version: "0.1.0"  # src/agentforge/main.py FastAPI(version=...)
last_migration_number: "0010"  # migrations 0001-0010
current_frontend_status: "none — backend/API only; Phase 7 will add React UI consuming existing APIs"

test_status: "419 passed, 22 integration deselected (keyless lane green)"
last_successful_test_command: "pytest -m 'not integration' -q"  # run via .venv/bin/python

completed_phases:
  - "1 Foundation"
  - "2 Core RAG"
  - "3 Agentic Layer"
  - "4 Multi-Agent"
  - "5 Enterprise Controls"
  - "6 Observability"
remaining_phases:
  - "7 React Frontend"
  - "8 Third-party Integrations (Slack/Gmail/Drive/GitHub)"
  - "9 Cloud Deployment"

active_specifications:
  # all complete: requirements + design + tasks; mirrored to /projects/sandbox/new-project/.kiro/specs/
  - agentforge-foundation-rag
  - agentforge-agentic-layer
  - agentforge-multi-agent
  - agentforge-enterprise
  - agentforge-observability
pending_specifications:
  - agentforge-frontend  # Phase 7, not yet created

open_todos:
  - "Task 19 (final full-suite checkpoint) left unchecked in agentforge-observability/tasks.md for user"
  - "GenerationResult has no model field; Instrumented_Provider uses provider as model name (_model_of)"
  - "Guardrail entry-point wrapping uses tolerant get_optional_guardrail_pipeline (skips when observability context unwired)"

known_blockers: "none blocking; awaiting user approval/merge of PR #11; force-push unreliable in sandbox (use new branches)"

important_assumptions:
  - "keyless + deterministic by default (no credentials needed to run/test)"
  - "PRs stacked (main = Phases 1-2; #3=P3, #6=P4, #8=P5, #11=P6); none merged to main beyond Phases 1-2"
  - "specs mirrored to new-project for UI panel"

current_dependency_versions:
  python: ">=3.11"
  fastapi: "0.115.6"
  "uvicorn[standard]": "0.34.0"
  pydantic: "2.10.4"
  pydantic-settings: "2.7.1"
  sqlalchemy: "2.0.36"
  asyncpg: "0.30.0"
  "psycopg[binary]": "3.2.3"
  pgvector: "0.3.6"
  chromadb: "0.5.23"
  sentence-transformers: "3.3.1"
  redis: "5.2.1"
  pypdf: "5.1.0"
  markdown: "3.7"
  python-multipart: "0.0.20"
  groq: "0.13.1"
  langgraph: "1.2.7"
  langchain-core: "1.4.8"
  pyjwt: "2.10.1"
  argon2-cffi: "23.1.0"
  # dev extras
  pytest: "8.3.4"
  pytest-asyncio: "0.25.0"
  hypothesis: "6.123.2"
  httpx: "0.28.1"

architectural_constraints:
  - "keyless defaults (no credentials required to run/test)"
  - "concretes only in config/container.py"
  - "org_id tenant isolation at data layer (cross-tenant -> 404)"
  - "reuse seams (extend existing abstractions, do not fork)"
  - "SecretStr for optional secrets"
  - "AppError envelope for all error responses"
  - "additive migrations only"
  - "one phase at a time with user approval"
  - "push only via github power"

resume_checkpoint: >
  Phases 1-6 complete on branch feat/agentforge-observability (cbf449b), PR #11 open.
  Next: get user approval, create agentforge-frontend spec, branch feat/agentforge-frontend
  off feat/agentforge-observability. Read docs/PROJECT_STATE.md + docs/decisions.md +
  api/schemas.py first. Do NOT auto-start.
---

# AgentForge — Project State

Machine-readable state for future Kiro sessions. See front-matter for authoritative values.

## Snapshot
- Phase 6 (Production Observability) complete and in review on PR #11.
- Branch `feat/agentforge-observability` @ `cbf449b`, base `feat/agentforge-enterprise`.
- API `0.1.0`; migrations `0001`–`0010`; backend/API only (no frontend yet).

## Phases
- Complete: 1 Foundation, 2 Core RAG, 3 Agentic Layer, 4 Multi-Agent, 5 Enterprise Controls, 6 Observability.
- Remaining: 7 React Frontend, 8 Third-party Integrations (Slack/Gmail/Drive/GitHub), 9 Cloud Deployment.

## Tests
- `pytest -m 'not integration' -q` via `.venv/bin/python`.
- 419 passed, 22 integration deselected (keyless lane green).

## Specs
- Active (requirements+design+tasks complete): agentforge-foundation-rag, agentforge-agentic-layer, agentforge-multi-agent, agentforge-enterprise, agentforge-observability.
- Mirrored to `/projects/sandbox/new-project/.kiro/specs/` for the UI panel.
- Pending: agentforge-frontend (Phase 7, not created).

## Open TODOs
- Task 19 (final full-suite checkpoint) left unchecked in agentforge-observability/tasks.md.
- GenerationResult has no `model` field; Instrumented_Provider uses provider as model name (`_model_of`).
- Guardrail entry-point wrapping uses tolerant `get_optional_guardrail_pipeline` (skips when observability context unwired).

## Blockers / Assumptions
- No hard blockers; awaiting user approval/merge of PR #11.
- Force-push unreliable in sandbox — always push to new branches.
- PRs stacked: main = Phases 1-2; #3=P3, #6=P4, #8=P5, #11=P6. Nothing merged to main beyond Phases 1-2.

## Next Steps (do NOT auto-start)
1. Get user approval / merge PR #11.
2. Create `agentforge-frontend` spec (Phase 7).
3. Branch `feat/agentforge-frontend` off `feat/agentforge-observability`.
4. Read `docs/PROJECT_STATE.md`, `docs/decisions.md`, and `api/schemas.py` first.
