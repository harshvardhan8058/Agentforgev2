"""Tracing_Exporter seam (Pluggable Seam: tracing export).

The ``Tracing_Exporter`` **consumes** the existing ``Trace`` produced by the reused
``Trace_Recorder`` and forwards it to an external destination only when configured. It
never records steps itself and MUST NOT reimplement the recorder (Req 1.1, 9.1).

The keyless default is :class:`NoOp_Tracing_Exporter`, which makes no external call and
produces no external side effect (Req 1.3). :class:`LangSmith_Tracing_Exporter` is
selected only when a Tracing_Credential is present (Req 1.4); it maps the consumed
``Trace`` to an external run tree, tags it with ``org_id`` / ``user_id`` metadata
(Req 1.5), and wraps the forward in a guard that suppresses **any** exception so trace
export never changes a run's outcome (Req 1.7).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
from uuid import UUID

from agentforge.tracing.base import Trace

if TYPE_CHECKING:  # pragma: no cover - typing only
    from agentforge.config.settings import Settings


class Tracing_Exporter(ABC):
    """Abstract contract for forwarding a completed Trace to an external destination."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Stable identifier for this exporter (e.g. ``"noop"``, ``"langsmith"``)."""
        raise NotImplementedError

    @abstractmethod
    def export(self, trace: Trace, *, org_id: UUID, user_id: UUID | None) -> None:
        """Forward ``trace``, tagged with the owning ``org_id`` and initiating ``user_id``.

        MUST NOT propagate an external failure to the caller: any error is caught and
        suppressed so trace export never changes a run's outcome (Req 1.5, 1.7).
        """
        raise NotImplementedError


class NoOp_Tracing_Exporter(Tracing_Exporter):
    """Keyless default: makes no external call and produces no external side effect."""

    @property
    def name(self) -> str:
        return "noop"

    def export(self, trace: Trace, *, org_id: UUID, user_id: UUID | None) -> None:
        return  # intentionally does nothing (Req 1.3)


class LangSmith_Tracing_Exporter(Tracing_Exporter):
    """LangSmith-backed exporter, selected only when a Tracing_Credential is present.

    Maps the consumed ``Trace`` to an external run tree, tags it with ``org_id`` /
    ``user_id`` metadata, and wraps the forward in a ``try/except`` that suppresses any
    exception so export never changes a run's outcome (Req 1.4, 1.5, 1.7).

    The external client is injectable (``client=``) so tests can supply a capturing or
    raising fake; a real client is constructed lazily only when none is injected and a
    credential is present.
    """

    def __init__(
        self, api_key: str, *, project: str = "agentforge", client=None
    ) -> None:
        self._api_key = api_key
        self._project = project
        self._client = client

    @property
    def name(self) -> str:
        return "langsmith"

    def export(self, trace: Trace, *, org_id: UUID, user_id: UUID | None) -> None:
        """Forward ``trace`` to LangSmith, tagging it with org/user metadata (Req 1.5).

        Any failure raised while building the client or forwarding the run is swallowed
        so trace export can never turn a successful run into a failure (Req 1.7).
        """
        try:
            client = self._get_client()
            run = self._to_run(trace, org_id=org_id, user_id=user_id)
            client.create_run(**run)
        except Exception:  # noqa: BLE001 - suppression is the contract (Req 1.7)
            # Swallowed deliberately: export must never alter the request outcome.
            return

    def _get_client(self):
        """Return the injected client, or lazily construct the real LangSmith client."""
        if self._client is not None:
            return self._client
        from langsmith import Client  # imported lazily so keyless boot needs no dep

        self._client = Client(api_key=self._api_key)
        return self._client

    def _to_run(
        self, trace: Trace, *, org_id: UUID, user_id: UUID | None
    ) -> dict:
        """Map the consumed ``Trace`` to a LangSmith run-tree payload (Req 1.5, 9.1).

        The payload carries the org/user tags in ``extra["metadata"]`` and the ordered
        trace entries as serialized outputs; it never re-records the trace itself.
        """
        return {
            "name": f"agent-run-{trace.run_id}",
            "run_type": "chain",
            "project_name": self._project,
            "inputs": {"run_id": trace.run_id},
            "outputs": {
                "entries": [
                    {
                        "ordinal": entry.ordinal,
                        "step_type": entry.step_type,
                        "tool_name": entry.tool_name,
                        "outcome": entry.outcome,
                    }
                    for entry in trace.entries
                ]
            },
            "extra": {
                "metadata": {
                    "org_id": str(org_id),
                    "user_id": str(user_id) if user_id is not None else None,
                }
            },
        }


def build_tracing_exporter(settings: Settings) -> Tracing_Exporter:
    """Select the active Tracing_Exporter from ``Settings`` (invoked by the container).

    Returns :class:`NoOp_Tracing_Exporter` when
    ``settings.active_tracing_exporter() == "noop"`` (the keyless default, so no external
    tracer is constructed), otherwise a :class:`LangSmith_Tracing_Exporter` reading the
    Tracing_Credential (Req 1.2, 1.4).
    """
    if settings.active_tracing_exporter() == "noop":
        return NoOp_Tracing_Exporter()
    return LangSmith_Tracing_Exporter(
        api_key=settings.langsmith_api_key.get_secret_value(),
        project=settings.langsmith_project,
    )
