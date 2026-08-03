"""Webhook transports: the real HTTP one, and a recording double for tests.

:class:`Httpx_Webhook_Transport` is the only place in the platform that dials a
tenant-supplied address, so every defence lives here rather than being assumed elsewhere:

* **The URL is re-validated on every attempt.** A subscription created against a public host
  can be repointed at an internal one afterwards; validating only at creation would be a
  check an attacker waits out.
* **Redirects are refused.** ``follow_redirects=False`` is what stops a public URL from
  handing off to ``169.254.169.254`` after admission.
* **The response body is never read.** The transport streams the response and looks only at
  the status line, so a malicious endpoint cannot answer a webhook with a gigabyte and make
  the platform hold it in memory. Nothing here ever has a body to hold.
* **The environment is not trusted.** ``trust_env=False`` keeps ``HTTPS_PROXY`` and
  ``NO_PROXY`` from redirecting deliveries somewhere the admission check never saw.
* **Nothing raises.** The contract in :class:`~agentforge.webhooks.base.Webhook_Transport` is
  that a failure is data. The broad ``except`` is deliberate and is the reason emitting can
  never affect the work that triggered it.

The timeout is per network operation (connect, write, read), not a wall-clock deadline for the
whole attempt — that is what the HTTP client can express. The emitter bounds the whole
sequence separately; the residual case of an endpoint that dribbles response headers slower
than the read timeout, forever, is bounded by that.
"""

from __future__ import annotations

import logging

from agentforge.webhooks.base import Transport_Result, Webhook_Transport
from agentforge.webhooks.security import WebhookUrlRejected, assert_deliverable_url

logger = logging.getLogger(__name__)

#: The longest failure summary stored on a delivery row or shown in the console. Bounded
#: because it comes from an exception whose text is not under this codebase's control.
MAX_ERROR_LENGTH = 200


def _summarise(exc: BaseException) -> str:
    """Return a short, type-led failure summary for a delivery row.

    The exception *type* leads because it is the part that is reliably meaningful
    (``ConnectTimeout`` vs ``ConnectError``); the message is appended, truncated, and comes
    from the client library rather than from the endpoint's response.
    """
    text = f"{type(exc).__name__}: {exc}".strip()
    if len(text) > MAX_ERROR_LENGTH:
        return text[: MAX_ERROR_LENGTH - 1] + "\u2026"
    return text


class Httpx_Webhook_Transport(Webhook_Transport):
    """Delivers webhooks over HTTPS with redirects disabled and the body never read."""

    def __init__(self, *, allow_loopback: bool = False) -> None:
        self._allow_loopback = allow_loopback

    def post(
        self, url: str, body: bytes, headers: dict[str, str], *, timeout_seconds: float
    ) -> Transport_Result:
        """POST ``body`` to ``url`` once; report the outcome and never raise."""
        try:
            assert_deliverable_url(url, allow_loopback=self._allow_loopback)
        except WebhookUrlRejected as exc:
            # Not a delivery failure so much as a refusal: the destination stopped being
            # acceptable between creation and now. Reported with the rule that was broken and
            # never with the address it resolved to.
            return Transport_Result(
                delivered=False, response_status=None, error=f"url rejected: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 - the seam must not raise (see module docstring)
            logger.warning("Webhook URL re-validation failed unexpectedly.", exc_info=True)
            return Transport_Result(
                delivered=False, response_status=None, error=_summarise(exc)
            )

        try:
            import httpx

            with httpx.Client(
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(timeout_seconds),
            ) as client:
                # ``stream`` rather than ``post``: this returns once the status line and
                # headers are in, leaving the body unread on the wire, where an untrusted
                # response belongs.
                with client.stream("POST", url, content=body, headers=headers) as response:
                    code = response.status_code
            delivered = 200 <= code < 300
            return Transport_Result(
                delivered=delivered,
                response_status=code,
                error=None if delivered else f"endpoint returned HTTP {code}",
            )
        except Exception as exc:  # noqa: BLE001 - the seam must not raise
            return Transport_Result(
                delivered=False, response_status=None, error=_summarise(exc)
            )


class Recording_Webhook_Transport(Webhook_Transport):
    """In-process transport that records deliveries instead of performing them.

    The keyless/test counterpart to :class:`Httpx_Webhook_Transport`, living beside it for the
    same reason ``Fake_Clock_Rate_Limiter`` lives beside the Redis limiter: the double is part
    of the seam's contract, and keeping it here means the emitter's retry behaviour is tested
    against the interface every real implementation must honour.

    ``succeed_from_attempt`` makes retry behaviour expressible without patching: 1 succeeds
    immediately, 2 fails once then succeeds, and ``None`` never succeeds.
    """

    def __init__(
        self, *, succeed_from_attempt: int | None = 1, response_status: int = 200
    ) -> None:
        self._succeed_from_attempt = succeed_from_attempt
        self._response_status = response_status
        #: Every attempt, in order, as ``(url, body, headers)``.
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    @property
    def attempts(self) -> int:
        """Number of attempts recorded so far."""
        return len(self.calls)

    def post(
        self, url: str, body: bytes, headers: dict[str, str], *, timeout_seconds: float
    ) -> Transport_Result:
        self.calls.append((url, body, dict(headers)))
        attempt = len(self.calls)
        if (
            self._succeed_from_attempt is not None
            and attempt >= self._succeed_from_attempt
        ):
            return Transport_Result(
                delivered=True, response_status=self._response_status, error=None
            )
        return Transport_Result(
            delivered=False, response_status=500, error="endpoint returned HTTP 500"
        )
