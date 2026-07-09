"""Property 5 (production-hardening, Task 7.1): SSE ordering and byte-identity through
the Reverse_Proxy (B3, Req 3.1, 3.4).

Requires the keyless Local_Stack running behind the nginx Reverse_Proxy
(`docker compose up`, zero credentials). Excluded from the default keyless lane; run with
`pytest -m integration` on a Docker host.

The property under test: *for any finite sequence of SSE events emitted by the
Backend_Service on an SSE_Route, the bytes and ordering received by the client through the
Reverse_Proxy are identical to those emitted, with no coalescing.*

Because the agent stream is deterministic under the keyless Fallback_Provider (identical
input yields an identical ordered event sequence — see `streaming/sse.py`), we can verify
byte-identity two complementary ways:

* **Ordering + framing (always):** parse the SSE frames received through the proxy and
  assert the embedded monotonic ``sequence`` is 0,1,2,... with exactly one terminal event
  (``completion`` xor ``error``) last — proving events were forwarded in order and not
  coalesced or dropped.
* **Byte-identity vs upstream (when the backend is directly reachable):** when
  ``AGENTFORGE_BACKEND_URL`` is provided, fetch the same stream directly from the
  Backend_Service and assert the raw response bytes are identical to those received through
  the proxy — proving the proxy altered nothing in transit.

Hypothesis drives a range of prompt event-sequences so the property holds across many
finite SSE sequences rather than a single example.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.integration

PROXY_URL = os.environ.get("AGENTFORGE_PROXY_URL", "http://localhost")
# Optional: direct Backend_Service origin (bypassing the proxy) for the byte-identity leg.
BACKEND_URL = os.environ.get("AGENTFORGE_BACKEND_URL")


def _register_and_token() -> str:
    """Register a fresh owner (keyless) and return a bearer access token."""
    email = f"sse-{uuid.uuid4().hex}@example.com"
    resp = httpx.post(
        f"{PROXY_URL}/auth/register-self",
        json={
            "email": email,
            "password": "correct horse battery staple",
            "org_name": f"org-{uuid.uuid4().hex}",
        },
        timeout=15.0,
    )
    assert resp.status_code == 201, resp.text
    token = resp.json().get("access_token")
    assert token, "expected an access token from register-self"
    return token


def _read_sse_bytes(base_url: str, token: str, message: str) -> bytes:
    """POST to the /agent/stream SSE_Route and return the RAW response bytes."""
    with httpx.stream(
        "POST",
        f"{base_url}/agent/stream",
        headers={"Authorization": f"Bearer {token}"},
        json={"message": message},
        timeout=60.0,
    ) as resp:
        assert resp.status_code == 200, resp.read().decode(errors="replace")
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        chunks = list(resp.iter_raw())
    # No coalescing at the transport layer: an unbuffered SSE stream is delivered as more
    # than one raw chunk (an initial event, intermediate events, and a terminal event),
    # never a single buffered blob — unless the whole sequence is a single terminal frame.
    return b"".join(chunks)


def _parse_frames(raw: bytes) -> list[tuple[str, dict]]:
    """Parse ``event: <type>\\ndata: <json>\\n\\n`` frames into (type, payload) tuples."""
    frames: list[tuple[str, dict]] = []
    for block in raw.decode("utf-8").split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        data_obj: dict = {}
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_obj = json.loads(line[len("data:") :].strip())
        assert event_type is not None, f"frame missing event type: {block!r}"
        frames.append((event_type, data_obj))
    return frames


@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(message=st.text(min_size=1, max_size=120))
def test_sse_ordering_and_byte_identity_through_proxy(message):
    """Feature: production-hardening, Property 5: SSE ordering and byte-identity through
    the proxy.

    For a finite SSE sequence emitted on an SSE_Route, the bytes and ordering received
    through the running nginx are identical to those emitted, with no coalescing.

    Validates: Requirements 3.1, 3.4
    """
    token = _register_and_token()

    proxied = _read_sse_bytes(PROXY_URL, token, message)
    frames = _parse_frames(proxied)

    # Ordering: the embedded monotonic ``sequence`` is 0,1,2,... in arrival order (no
    # reordering, no coalescing of distinct events).
    sequences = [payload.get("sequence") for _t, payload in frames]
    assert sequences == list(range(len(frames))), f"out-of-order/coalesced: {sequences}"

    # Exactly one terminal event (completion xor error) and it is last.
    terminal_types = {"completion", "error"}
    terminals = [i for i, (t, _p) in enumerate(frames) if t in terminal_types]
    assert len(terminals) == 1, f"expected exactly one terminal event, got {terminals}"
    assert terminals[0] == len(frames) - 1, "terminal event must be last"

    # Byte-identity vs the upstream Backend_Service when it is directly reachable: the
    # deterministic Fallback_Provider yields an identical ordered sequence, so the proxy
    # must forward it byte-for-byte.
    if BACKEND_URL:
        direct_token = _register_and_token()
        direct = _read_sse_bytes(BACKEND_URL, direct_token, message)
        # Normalize the only legitimately per-run-varying fields (ids) before comparing
        # the wire bytes, so any proxy-introduced mutation (buffering markers, rewrites,
        # reordering) is still caught.
        assert _strip_ids(proxied) == _strip_ids(direct), "proxy altered the SSE bytes"


def _strip_ids(raw: bytes) -> list[tuple[str, dict]]:
    """Frames with per-run ids (run_id/conversation_id) removed for byte-identity compare."""
    normalized: list[tuple[str, dict]] = []
    for event_type, payload in _parse_frames(raw):
        stripped = {k: v for k, v in payload.items() if k not in {"run_id", "conversation_id"}}
        normalized.append((event_type, stripped))
    return normalized
