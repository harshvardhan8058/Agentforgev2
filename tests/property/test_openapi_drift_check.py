"""Property 7 (production-hardening, Task 10.4): the drift check is sound, keyless, and
deterministic (B6, Req 6.3, 6.4, 6.5).

Fully keyless: `create_app().openapi()` reads no credential and the drift comparison is a
pure function over dict structures. For any injected synthetic divergence (adding a route,
removing a route, or modifying an operation) the checker reports failure and names the
differing route; for an identical contract it reports success; and repeated runs on
unchanged inputs return the same result. Hypothesis drives ≥100 divergence examples.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import check_openapi  # noqa: E402

from agentforge.main import create_app  # noqa: E402

# The keyless-generated contract used as the identity baseline for every case.
_BASELINE = create_app().openapi()
_PATHS = sorted(_BASELINE.get("paths", {}))


def _path_and_method(path: str):
    item = _BASELINE["paths"][path]
    methods = [m for m in item if m in {"get", "put", "post", "delete", "patch"}]
    return path, methods[0] if methods else "get"


# Feature: production-hardening, Property 7: drift check is sound, keyless, and deterministic
def test_identity_contract_reports_success():
    """A contract equal to the generated one yields no differences (success)."""
    assert check_openapi.diff_contracts(_BASELINE, copy.deepcopy(_BASELINE)) == []


# Feature: production-hardening, Property 7: drift check is sound, keyless, and deterministic
@hyp_settings(max_examples=150, deadline=None)
@given(
    kind=st.sampled_from(["add", "remove", "modify"]),
    path_index=st.integers(min_value=0, max_value=max(0, len(_PATHS) - 1)),
    new_suffix=st.text(
        alphabet="abcdefghijklmnopqrstuvwxyz", min_size=1, max_size=12
    ),
)
def test_injected_divergence_is_detected_and_named(kind, path_index, new_suffix):
    """Feature: production-hardening, Property 7: drift check is sound, keyless, and
    deterministic.

    For an add/remove/modify divergence, the checker fails and names the differing route;
    an identical contract passes; and the result is deterministic.

    Validates: Requirements 6.3, 6.4, 6.5
    """
    generated = _BASELINE
    committed = copy.deepcopy(_BASELINE)
    target_path = _PATHS[path_index]
    _, method = _path_and_method(target_path)

    if kind == "add":
        # A route mounted (generated) but absent from the committed contract.
        extra_path = f"/synthetic-{new_suffix}"
        committed["paths"].pop(extra_path, None)
        # Ensure the "generated" side has a route the committed side lacks by adding it to
        # generated only (via a local copy so the shared baseline is untouched).
        generated = copy.deepcopy(_BASELINE)
        generated["paths"][extra_path] = {"get": {"responses": {"200": {"description": "ok"}}}}
        expected_fragment = f"GET {extra_path}"
        expected_reason = "missing from committed contract"
    elif kind == "remove":
        # A route present in committed but not mounted (removed from generated side).
        generated = copy.deepcopy(_BASELINE)
        generated["paths"].pop(target_path)
        expected_fragment = f"{method.upper()} {target_path}"
        expected_reason = "extra in committed contract"
    else:  # modify
        # Same routes, but one operation definition differs.
        committed["paths"][target_path][method] = {
            **copy.deepcopy(committed["paths"][target_path][method]),
            "summary": f"drifted-{new_suffix}",
        }
        expected_fragment = f"{method.upper()} {target_path}"
        expected_reason = "operation differs"

    differences = check_openapi.diff_contracts(generated, committed)

    # Soundness: the divergence is detected ...
    assert differences, f"expected drift to be detected for kind={kind}"
    # ... and the offending route is named with the right reason.
    assert any(
        expected_fragment in d and expected_reason in d for d in differences
    ), f"expected '{expected_reason}' naming '{expected_fragment}', got {differences}"

    # Determinism: the same inputs produce the same result.
    assert differences == check_openapi.diff_contracts(generated, committed)
