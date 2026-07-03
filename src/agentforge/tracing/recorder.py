"""Trace recorders — in-memory (keyless default) and Postgres-backed (stub).

Will provide an in-memory ``Trace_Recorder`` (keyless default) and a Postgres-backed
recorder that appends entries with the next ordinal and returns them ordered by ordinal,
wired into the orchestrator nodes (Req 10.1-10.4). Implemented in a later task (see task
12.2); this module is a scaffolding placeholder.
"""

from __future__ import annotations
