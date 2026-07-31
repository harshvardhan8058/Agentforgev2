"""The outbound HTTP transport for webhook delivery, and its recording double.

Every outbound limit lives here, in one place, so a reviewer can see all of them at once:

* **Redirects disabled.** A 302 would otherwise walk a validated request to an unvalidated
  address, defeating the whole URL admission policy.
* **A bounded timeout** per attempt, supplied by the emitter. Note precisely what httpx's
  timeout is: a bound on each individual connect/write/read operation, **not** a deadline on
  the whole attempt. An endpoint that drips one byte per interval can therefore stretch an
  attempt beyond the nominal figure. Reading only the response head (below) removes the
  unbounded part of that; the residual is documented in ``docs/KNOWN_LIMITATIONS.md``.
* **The response body is never read.** Only the status matters for delivery, and a tenant's
  endpoint may return material this platform has no business storing or logging. This is
  enforced with ``client.stream(...)``, exited without touching the body — ``client.post``
  would buffer the entire response first, so an endpoint returning a multi-gigabyte body would
  cost this process that memory even though nothing ever looked at it.
* **Re-validation before connecting.** DNS is mutable, so the stored URL is re-checked on every
  attempt rather than trusted (see ``webhooks/security.py``).
* **No exception escapes.** A transport failure is a :class:`Transport_Result`, not an error —
  the emitter's retry logic is a decision, not an exception handler.
"""

from __future__ import annotations

import logging

from agentforge.webhooks.base import Transport_Result, Webhook_Transport
from agentforge.webhooks.security import WebhookUrlRejected, assert_deliverable_url

logger = logging.getLogger(__name__)

#: Diagnostics are stored in the delivery log a tenant can read, so they are bounded.
MAX_ERROR_LENGTH = 200


def _short(message: str) -> str:
    return message if len(message) <= MAX_ERROR_LENGTH else message[: MAX_ERROR_LENGTH - 1] + "…"


class Httpx_Webhook_Transport(Webhook_Transport):
    """Real HTTP delivery over ``httpx``.

    ``allow_loopback`` mirrors the URL admission policy's development allowance and is set by
    the composition root outside the production profile only.
    """

    def __init__(self, *, allow_loopback: bool = False) -> None:
        self._allow_loopback = allow_loopback

    def post(
        self, url: str, *, body: bytes, headers: dict[str, str], timeout_seconds: float
    ) -> Transport_Result:
        try:
            assert_deliverable_url(url, allow_loopback=self._allow_loopback)
        except WebhookUrlRejected as exc:
            # A subscription whose host has since been re-pointed at an internal address. Not
            # retried by the emitter's error path being different — it will retry and fail the
            # same way, which is correct: the endpoint is not deliverable to.
            return Transport_Result(status=None, error=_short(f"url rejected: {exc}"))

        try:
            import httpx
        except ImportError:  # pragma: no cover - httpx is a runtime dependency
            return Transport_Result(status=None, error="httpx is not installed")

        try:
            with httpx.Client(
                follow_redirects=False, timeout=timeout_seconds, trust_env=False
            ) as client:
                # `stream` rather than `post`: the response head is all this needs, and the body
                # is closed unread on exit. `post` would buffer the whole thing first.
                with client.stream("POST", url, content=body, headers=headers) as response:
                    return Transport_Result(status=response.status_code)
        except Exception as exc:  # noqa: BLE001 - transport failure is a result, not an error
            # Deliberately `Exception`, not httpx's own hierarchy: URL re-validation and the
            # client itself can both raise types outside it (a malformed port is a ValueError),
            # and this seam's contract is that a failure is a *result*. The exception TYPE plus
            # a bounded message is enough for an operator to tell a timeout from a TLS failure,
            # without storing anything the tenant's endpoint sent back.
            return Transport_Result(
                status=None, error=_short(f"{type(exc).__name__}: {exc}")
            )


class Recording_Webhook_Transport(Webhook_Transport):
    """Test double: records what would have been sent and returns a scripted result.

    Lives beside the real transport rather than in the test tree so the emitter's tests, the
    API tests and any future consumer share one double — three divergent fakes of one seam is
    how a fake starts disagreeing with the thing it stands for.
    """

    def __init__(self, *, status: int | None = 200, error: str | None = None) -> None:
        self.status = status
        self.error = error
        self.calls: list[dict[str, object]] = []
        #: Set to make the Nth call succeed after earlier failures (retry tests).
        self.succeed_from_attempt: int | None = None

    def post(
        self, url: str, *, body: bytes, headers: dict[str, str], timeout_seconds: float
    ) -> Transport_Result:
        self.calls.append(
            {
                "url": url,
                "body": body,
                "headers": dict(headers),
                "timeout_seconds": timeout_seconds,
            }
        )
        if (
            self.succeed_from_attempt is not None
            and len(self.calls) >= self.succeed_from_attempt
        ):
            return Transport_Result(status=200)
        return Transport_Result(status=self.status, error=self.error)
