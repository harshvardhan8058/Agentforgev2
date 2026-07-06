"""Integration_Layer core — error vocabulary, connector seam, and the Integration_Tool base.

This module holds the cross-cutting Phase 8 machinery every integration reuses:

* the fixed, closed :class:`IntegrationErrorCode` vocabulary carried in
  ``Tool_Result.data["error_code"]`` inside a run and rendered through ``AppError.code`` on
  HTTP surfaces (Req 7.x);
* the connector failure classes (:class:`ConnectorError` and its subclasses) a credentialed
  connector raises, which the base Tool maps onto the vocabulary — the Tool never inspects
  provider-specific error text (Req 7.2–7.4). Their messages carry no credential value and
  no internal stack trace (Req 7.6);
* the :class:`Integration_Connector` marker ABC exposing the ``available`` flag each Tool
  mirrors (Req 5.5); and
* the :class:`Integration_Tool` base (a ``Tool_Interface`` subclass) capturing availability
  mirroring, the Disabled short-circuit, bounded-timeout enforcement, error mapping, result
  capping, and credential-free result construction, so each concrete tool only declares its
  identity, schema, and action dispatch.

The design mirrors the ``Search_Provider`` seam (``tools/search``) exactly and forks none of
the existing Tool / Registry / Tool_Result contracts.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from enum import Enum
from typing import Callable

from agentforge.tools.base import Tool_Interface, Tool_Result


class IntegrationErrorCode(str, Enum):
    """The closed vocabulary of integration failure codes (Req 7.1–7.4, 6.2).

    Carried in ``Tool_Result.data["error_code"]`` inside a run and rendered through
    ``AppError.code`` on HTTP surfaces. This is the complete, fixed set; no other code is
    ever surfaced by the Integration_Layer.
    """

    DISABLED = "integration_disabled"
    UNAUTHORIZED = "integration_unauthorized"
    RATE_LIMITED = "integration_rate_limited"
    UPSTREAM_ERROR = "integration_upstream_error"
    TIMEOUT = "integration_timeout"


class ConnectorError(RuntimeError):
    """Base transport failure raised by a credentialed (Keyed) connector.

    Messages are constructed from fixed strings only and carry **no** credential value and
    **no** internal stack trace (Req 7.6). The base Tool maps each subclass onto the fixed
    :class:`IntegrationErrorCode` vocabulary without inspecting provider-specific text.
    """


class Unauthorized_Error(ConnectorError):
    """The third-party service rejected the credential (→ ``integration_unauthorized``)."""


class Rate_Limited_Error(ConnectorError):
    """The third-party service applied a rate limit (→ ``integration_rate_limited``)."""


class Upstream_Error(ConnectorError):
    """The third-party service returned an upstream error (→ ``integration_upstream_error``)."""


class _TimeoutExceeded(RuntimeError):
    """Internal signal raised by the timeout wrapper when the Timeout_Budget is exceeded.

    Never surfaced directly; the base Tool maps it onto ``integration_timeout`` (Req 6.2).
    """


class Integration_Connector(ABC):
    """Shared marker contract for every per-integration connector (mirrors Search_Provider).

    Each integration defines its own connector contract subclassing this and adding exactly
    its operations. The one thing every connector shares is the ``available`` flag the Tool
    mirrors so a Disabled integration is never offered to the agent (Req 5.1, 5.5).
    """

    @property
    @abstractmethod
    def available(self) -> bool:
        """Whether calls can be performed (i.e. a Credential is configured)."""
        raise NotImplementedError


class Integration_Tool(Tool_Interface):
    """Base ``Tool_Interface`` implementation shared by every Integration_Tool.

    Captures the cross-cutting behavior so each concrete tool only supplies its ``name`` /
    ``description`` / ``input_schema`` and a ``_dispatch`` routing a validated action to a
    connector operation:

    * ``available`` mirrors the connector (Req 5.5);
    * ``invoke`` short-circuits a Disabled tool with ``integration_disabled`` and **no**
      connector call (Req 7.1, 3.2);
    * the dispatched connector call runs under a bounded timeout mapped to
      ``integration_timeout`` on expiry (Req 6.1, 6.2);
    * each connector failure class maps onto the fixed vocabulary (Req 7.2–7.4);
    * any returned collection is capped to ``max_results`` (Req 6.3);
    * ``content`` / ``data`` are built from outcome fields only, so no credential is ever
      placed in a ``Tool_Result`` (Req 4.2, 4.4); and
    * a successful invocation returns ``Tool_Result(ok=True, ...)`` (Req 1.4).
    """

    def __init__(
        self,
        connector: Integration_Connector,
        *,
        timeout_seconds: float,
        max_results: int,
    ) -> None:
        self._connector = connector
        # Bounded, positive execution limits; guard against non-positive misconfiguration.
        self._timeout_seconds = max(float(timeout_seconds), 0.001)
        self._max_results = max(int(max_results), 0)

    @property
    def available(self) -> bool:
        """Mirror the connector so a Disabled integration is never offered (Req 5.5)."""
        return self._connector.available

    def invoke(self, arguments: dict) -> Tool_Result:
        """Execute the integration action with the full safety envelope.

        Never raises for an anticipated failure: every mapped failure is returned as a
        ``Tool_Result(ok=False)`` carrying a fixed ``error_code`` so the agent ``act`` node
        records a bounded observation and continues the run (Req 8.4).
        """
        # Disabled short-circuit: no connector call is ever made (Req 7.1, 3.2, 10.5).
        if not self._connector.available:
            return self._error_result(
                IntegrationErrorCode.DISABLED, "integration is disabled"
            )

        try:
            outcome = self._run_with_timeout(
                lambda: self._dispatch(arguments, self._connector)
            )
        except _TimeoutExceeded:
            return self._error_result(
                IntegrationErrorCode.TIMEOUT, "integration timed out"
            )
        except Unauthorized_Error:
            return self._error_result(
                IntegrationErrorCode.UNAUTHORIZED, "provider rejected the credential"
            )
        except Rate_Limited_Error:
            return self._error_result(
                IntegrationErrorCode.RATE_LIMITED, "provider applied a rate limit"
            )
        except (Upstream_Error, ConnectorError):
            # Any other transport failure maps to the generic upstream code (Req 7.4).
            return self._error_result(
                IntegrationErrorCode.UPSTREAM_ERROR, "provider returned an error"
            )

        return self._success_result(self._cap(outcome))

    # --- helpers -----------------------------------------------------------------

    def _run_with_timeout(self, fn: Callable[[], dict]) -> dict:
        """Run ``fn`` under the configured Timeout_Budget (Req 6.1, 6.2).

        The connector call runs on a worker thread; if it does not complete within
        ``timeout_seconds`` the wrapper abandons it and raises :class:`_TimeoutExceeded`.
        The abandoned worker is left to finish on its own (Python joins it at interpreter
        exit); the correctness guarantee is that ``invoke`` returns promptly with a timeout.
        """
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fn)
        try:
            result = future.result(timeout=self._timeout_seconds)
        except FuturesTimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            raise _TimeoutExceeded from None
        executor.shutdown(wait=False)
        return result

    def _cap(self, outcome: dict) -> dict:
        """Cap every returned collection to ``max_results`` (Req 6.3).

        Bounds the volume of data a single invocation returns; scalar fields pass through
        untouched. Never exceeds the configured maximum result count.
        """
        capped: dict = {}
        for key, value in outcome.items():
            if isinstance(value, list):
                capped[key] = value[: self._max_results]
            else:
                capped[key] = value
        return capped

    def _success_result(self, outcome: dict) -> Tool_Result:
        """Build a success ``Tool_Result`` from outcome fields only (Req 1.4, 4.4).

        A ``content`` key in ``outcome`` (if present) becomes the human-readable summary;
        the remaining fields become ``data``. No credential is ever placed here — the base
        only ever sees the connector's returned outcome, never the credential.
        """
        content = outcome.get("content")
        data = {key: value for key, value in outcome.items() if key != "content"}
        if content is None:
            content = self._default_summary(data)
        return Tool_Result(
            tool_name=self.name,
            ok=True,
            content=str(content),
            data=data,
        )

    def _error_result(
        self, code: IntegrationErrorCode, message: str
    ) -> Tool_Result:
        """Build a contained failure ``Tool_Result`` carrying a fixed error code (Req 7.x).

        ``message`` is a fixed, safe string containing no credential value and no internal
        stack trace (Req 7.6, 4.2).
        """
        return Tool_Result(
            tool_name=self.name,
            ok=False,
            content=message,
            data={"error_code": code.value},
        )

    @staticmethod
    def _default_summary(data: dict) -> str:
        """Derive a compact, credential-free summary when a subclass supplies none."""
        for key, value in data.items():
            if isinstance(value, list):
                return f"{len(value)} result(s)"
        return "ok"

    @abstractmethod
    def _dispatch(self, arguments: dict, connector: Integration_Connector) -> dict:
        """Route a validated action to a connector operation and return its outcome.

        Returns a plain dict outcome; the base caps its collections and builds the
        ``Tool_Result``. An optional ``content`` key becomes the summary. Must never place
        any credential value into the returned dict (Req 4.4).
        """
        raise NotImplementedError
