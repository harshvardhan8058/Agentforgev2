"""PgConversation_Store — Postgres-backed conversation persistence (stub).

Will implement ``Conversation_Store`` over the existing Postgres instance: ``create``
inserts a UUID conversation, ``append`` computes the next ordinal and auto-creates an
unknown conversation, and ``history`` returns messages in ascending ordinal order
(Req 8.1-8.5). Implemented in a later task (see task 11.2); this module is a scaffolding
placeholder.
"""

from __future__ import annotations
