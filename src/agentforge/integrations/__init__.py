"""Integration_Layer — Phase 8 third-party integrations (Slack, Gmail, Google Drive, GitHub).

This package delivers the four third-party integrations as pluggable ``Tool_Interface``
implementations discoverable by the Phase 3 agentic and Phase 4 multi-agent layers. It
reuses — never reimplements — every existing seam: the Tool contract (``tools/base.py``),
the ``Tool_Registry`` (``tools/registry.py``), the ``Settings`` loader
(``config/settings.py``), the composition root (``config/container.py``), the uniform
``AppError`` envelope (``api/errors.py``), and the Phase 5/6 enterprise and observability
layers.

Each integration's network work sits behind a per-integration Connector transport seam
mirroring the ``Search_Provider`` keyless/credentialed/mockable pattern, so every
integration is Disabled when its credential is absent, is registered only in the
composition root, maps its failures onto a fixed error-code vocabulary, executes under a
bounded timeout, and is fully testable keyless with a mock Connector requiring no real
credential and no network.
"""

from __future__ import annotations

# The canonical, stable ordering of the four integrations, used across the subsystem
# (Settings enablement, the composition-root builders, and the Integration_Status view).
INTEGRATION_NAMES: tuple[str, ...] = ("slack", "gmail", "google_drive", "github")

__all__ = ["INTEGRATION_NAMES"]
