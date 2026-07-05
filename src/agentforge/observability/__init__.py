"""Observability_Layer (Phase 6): the production-observability subsystem.

This package adds pluggable tracing export, token/cost analytics, a prompt registry,
guardrails, and an evaluation framework on top of the reused Phase 1-5 seams — all
keyless and deterministic by default. Every ``base.py`` holds abstract contracts;
sibling modules hold concrete implementations, and ``config/container.py`` is the only
module that names the concretes.
"""

from __future__ import annotations
