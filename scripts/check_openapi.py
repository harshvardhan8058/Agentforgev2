#!/usr/bin/env python
"""Keyless server-side OpenAPI contract drift check (production-hardening B6, Req 6.3-6.5).

Builds the FastAPI app **keyless** (`create_app()` mounts every router without touching
infrastructure or reading any credential), serializes `app.openapi()`, and compares it to
the committed `frontend/openapi.json`. On a match it reports success and exits 0; on a
mismatch it exits non-zero and prints every differing path/method (added, removed, or
changed) so the drift is actionable. The check reads no credential and is deterministic —
the same inputs always produce the same result (Req 6.5).

This is the server-side complement to the client-side `frontend/scripts/check-codegen.mjs`
(which guards `schema.d.ts` vs `openapi.json`). Wire it into the keyless CI test job.

Usage:
    python scripts/check_openapi.py        # exits 1 on drift, 0 on match

Regenerate the contract after an intentional route change with:
    python -c "import json; from agentforge.main import create_app; \\
        open('frontend/openapi.json','w').write(json.dumps(create_app().openapi(), \\
        indent=2, sort_keys=True) + '\\n')"
    cd frontend && npm run codegen
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Repo root is the parent of this script's directory (scripts/ -> repo root).
REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_CONTRACT = REPO_ROOT / "frontend" / "openapi.json"

# Comparison helpers operate on plain dict structures so the result is independent of key
# ordering or serialization whitespace.
Contract = dict


def _methods(operations: dict) -> set[str]:
    """HTTP methods defined for a path item (ignore non-operation keys like parameters)."""
    http_methods = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
    return {m for m in operations if m.lower() in http_methods}


def diff_contracts(generated: Contract, committed: Contract) -> list[str]:
    """Return a sorted list of human-readable differences between two OpenAPI contracts.

    An empty list means the contracts are equal. Differences are reported at path,
    method, and (whole-contract) component granularity so a reader can locate each drift.
    """
    differences: list[str] = []

    gen_paths: dict = generated.get("paths", {})
    com_paths: dict = committed.get("paths", {})
    gen_path_set, com_path_set = set(gen_paths), set(com_paths)

    for path in sorted(gen_path_set - com_path_set):
        for method in sorted(_methods(gen_paths[path])):
            differences.append(f"missing from committed contract: {method.upper()} {path}")
    for path in sorted(com_path_set - gen_path_set):
        for method in sorted(_methods(com_paths[path])):
            differences.append(f"extra in committed contract (not mounted): {method.upper()} {path}")

    for path in sorted(gen_path_set & com_path_set):
        gen_methods = _methods(gen_paths[path])
        com_methods = _methods(com_paths[path])
        for method in sorted(gen_methods - com_methods):
            differences.append(f"missing from committed contract: {method.upper()} {path}")
        for method in sorted(com_methods - gen_methods):
            differences.append(f"extra in committed contract (not mounted): {method.upper()} {path}")
        for method in sorted(gen_methods & com_methods):
            if gen_paths[path][method] != com_paths[path][method]:
                differences.append(f"operation differs: {method.upper()} {path}")

    # Everything else (components/schemas, info, servers, ...) compared as a whole so that
    # e.g. a changed request/response schema shared across routes is still caught.
    for section in sorted(set(generated) | set(committed)):
        if section == "paths":
            continue
        if generated.get(section) != committed.get(section):
            differences.append(f"top-level section differs: {section!r}")

    return differences


def main() -> int:
    # Import here so a missing committed file is reported cleanly before app construction.
    from agentforge.main import create_app

    if not COMMITTED_CONTRACT.exists():
        print(f"ERROR: committed contract not found at {COMMITTED_CONTRACT}", file=sys.stderr)
        return 1

    generated: Contract = create_app().openapi()
    committed: Contract = json.loads(COMMITTED_CONTRACT.read_text(encoding="utf-8"))

    differences = diff_contracts(generated, committed)
    if differences:
        print(
            "OpenAPI contract drift detected: frontend/openapi.json is out of sync with the "
            "mounted routes.",
            file=sys.stderr,
        )
        for line in differences:
            print(f"  - {line}", file=sys.stderr)
        print(
            "\nRegenerate with app.openapi() and run `cd frontend && npm run codegen`, then "
            "commit both files.",
            file=sys.stderr,
        )
        return 1

    print("OpenAPI contract check passed — frontend/openapi.json matches the mounted routes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
