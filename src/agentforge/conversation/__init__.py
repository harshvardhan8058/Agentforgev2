"""Conversation (Phase 3): persistent multi-turn history.

The abstract ``Conversation_Store`` (``base.py``) persists Conversations and Messages in
Postgres and returns history in ordinal order; the concrete Postgres-backed store lives
in ``store.py`` (Req 8).
"""

from __future__ import annotations
