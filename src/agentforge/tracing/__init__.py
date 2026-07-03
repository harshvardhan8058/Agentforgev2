"""Tracing (Phase 3): lightweight observability of agent steps.

The abstract ``Trace_Recorder`` (``base.py``) records an ordered ``Trace`` of each
Agent_Step and exposes it so a later observability phase can consume it without modifying
the orchestrator; the in-memory and Postgres-backed recorders live in ``recorder.py``
(Req 10).
"""

from __future__ import annotations
