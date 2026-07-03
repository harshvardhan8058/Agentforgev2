"""Streaming (Phase 3): incremental Agent_Run output over Server-Sent Events.

The abstract ``Streaming_Service`` (``base.py``) yields typed ``StreamEvent``s in
production order with exactly one terminal event; the SSE implementation lives in
``sse.py`` (Req 9).
"""

from __future__ import annotations
