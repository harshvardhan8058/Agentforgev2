"""Property-based test: no credential is baked into any image or served asset.

Feature: agentforge-deployment, Property 1: No credential is baked into any image or
served asset.

*For any* built Backend_Image / Frontend_Image layer, served frontend asset (including
the generated ``config.js``), and committed ``*.env.example`` file, no real credential
value is present — only placeholders.

Validates: Requirements 10.2, 10.3, 10.5, 3.3, 8.5

This test is KEYLESS and deterministic (it only reads committed files and renders the
``config.js`` template in-process — no DB, no network, no Docker daemon). The image-layer
half of Property 1 is exercised by the CI ``build`` job, which ``docker save``s each
built image and runs ``scripts/scan_secrets.py --image-tar`` on it; the scanner used
there is the same one exercised here (``scan_image_tar`` / ``scan_text``), so its
detection behavior is validated by the controls below.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hypothesis import given
from hypothesis import settings as hyp_settings
from hypothesis import strategies as st

# Make the repo-root scripts/ importable so we exercise the SAME scanner CI runs.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import scan_secrets  # noqa: E402


# ---------------------------------------------------------------------------
# Smart generator: arbitrary NON-SECRET API_BASE_URL values a runtime config
# could plausibly carry — schemes, hosts, ports, and same-origin paths — drawn
# from a URL-shaped alphabet so no generated value is itself credential-shaped.
# ---------------------------------------------------------------------------
_host_label = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789-",
    min_size=1,
    max_size=12,
).filter(lambda s: not s.startswith("-") and not s.endswith("-"))

_hostname = st.lists(_host_label, min_size=1, max_size=4).map(lambda parts: ".".join(parts))

_path = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-", min_size=1, max_size=8),
    min_size=0,
    max_size=3,
).map(lambda segs: "/" + "/".join(segs) if segs else "/")


@st.composite
def api_base_urls(draw):
    """Generate plausible, non-secret base URLs (or None for the unset default)."""
    if draw(st.booleans()) and draw(st.integers(0, 4)) == 0:
        return None  # unset -> documented empty-config default
    scheme = draw(st.sampled_from(["http", "https"]))
    host = draw(_hostname)
    port = draw(st.one_of(st.none(), st.integers(min_value=1, max_value=65535)))
    path = draw(_path)
    authority = f"{host}:{port}" if port is not None else host
    return f"{scheme}://{authority}{path}"


@hyp_settings(max_examples=200)
@given(url=api_base_urls())
def test_config_js_render_carries_no_credential(url):
    """For any non-secret API_BASE_URL, the rendered config.js contains no credential."""
    rendered = scan_secrets.render_config_js(url)
    # The runtime config only ever carries the non-secret base URL.
    assert "__AGENTFORGE_CONFIG__" in rendered
    assert scan_secrets.scan_text(rendered, "config.js") == []


def test_committed_env_examples_contain_only_placeholders():
    """Every committed *.env.example has placeholder-only values (Req 10.3, 3.3)."""
    findings = scan_secrets.scan_env_examples()
    assert findings == [], "\n".join(str(f) for f in findings)


def test_built_frontend_dist_has_no_baked_secret():
    """When frontend/dist exists, no served asset carries a credential (Req 8.5, 10.2)."""
    findings = scan_secrets.scan_frontend_dist()
    assert findings == [], "\n".join(str(f) for f in findings)


def test_full_repo_scan_is_clean():
    """The aggregate repo scan (env + dist + config renders) reports no credential."""
    findings = scan_secrets.scan_repo()
    assert findings == [], "\n".join(str(f) for f in findings)


# ---------------------------------------------------------------------------
# Controls — the scanner MUST actually detect real credential shapes, otherwise
# a clean result above would be meaningless. These mirror the frontend controls.
# ---------------------------------------------------------------------------
def test_scanner_detects_real_credential_shapes():
    assert scan_secrets.scan_text('const k = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ012345";')
    assert scan_secrets.scan_text(
        'token="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.'
        'SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"'
    )
    assert scan_secrets.scan_text('apiKey: "super-secret-value-123"')
    assert scan_secrets.scan_text("-----BEGIN RSA PRIVATE KEY-----")
    assert scan_secrets.scan_text('AWS="AKIAIOSFODNN7EXAMPLE"')
    # A real value assigned to a secret-bearing env key is flagged.
    assert scan_secrets.scan_env_text("JWT_SECRET=s3cr3t-actual-deadbeef-value")


def test_scanner_ignores_placeholders_and_benign_strings():
    # Placeholder env values are NOT flagged.
    assert scan_secrets.scan_env_text("JWT_SECRET=REPLACE_WITH_LONG_RANDOM_SECRET") == []
    assert scan_secrets.scan_env_text("POSTGRES_PASSWORD=REPLACE_PASSWORD") == []
    assert scan_secrets.scan_env_text("GROQ_API_KEY=") == []
    assert scan_secrets.scan_env_text("DATABASE_URL=${DATABASE_URL}") == []
    assert scan_secrets.scan_env_text("JWT_ALGORITHM=HS256") == []
    # Benign framework strings are NOT flagged.
    assert scan_secrets.scan_text('const types = ["text","password","email"];') == []
    assert scan_secrets.scan_text('headers.set("Authorization", `Bearer ${token}`)') == []
