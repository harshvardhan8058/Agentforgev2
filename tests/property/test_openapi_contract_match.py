"""Property 6 (production-hardening, Task 10.3): the committed API contract matches the
mounted routes exactly (B6, Req 6.1, 6.2, 7.2, 7.3).

Deterministic and fully keyless: `create_app()` mounts every router without touching
infrastructure or reading any credential, and the committed `frontend/openapi.json` is read
from disk. The property: the committed contract equals `app.openapi()` — every mounted route
present, nothing extra — which also guarantees no existing route/field was removed relative
to the mounted surface.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_openapi  # noqa: E402

from agentforge.main import create_app  # noqa: E402

_COMMITTED = _REPO_ROOT / "frontend" / "openapi.json"


# Feature: production-hardening, Property 6: committed contract matches the mounted routes exactly
def test_committed_contract_equals_mounted_routes():
    """Feature: production-hardening, Property 6: committed contract matches the mounted
    routes exactly.

    The committed frontend/openapi.json equals app.openapi(): every mounted route is
    present with a matching operation definition, and nothing extra is present.

    Validates: Requirements 6.1, 6.2, 7.2, 7.3
    """
    generated = create_app().openapi()
    committed = json.loads(_COMMITTED.read_text(encoding="utf-8"))

    differences = check_openapi.diff_contracts(generated, committed)
    assert differences == [], "committed contract drifted from mounted routes:\n" + "\n".join(
        differences
    )

    # `GET /integrations/status` must be present in the committed contract (the specific
    # route the audit found missing).
    assert "/integrations/status" in committed["paths"]
    assert "get" in committed["paths"]["/integrations/status"]


# Feature: production-hardening, Property 6: committed contract matches the mounted routes exactly
def test_contract_match_is_deterministic():
    """app.openapi() is stable across repeated builds, so the match result is reproducible."""
    first = create_app().openapi()
    second = create_app().openapi()
    assert check_openapi.diff_contracts(first, second) == []
