"""Long_Term_Memory — semantic recall over the existing Embedding_Provider + Vector_Store.

Long-term memory is *semantic recall across conversations*, which the existing
``Embedding_Provider`` + ``Vector_Store`` seams already provide — so this component reuses
them rather than reimplementing embedding or vector storage (Req 7.1, 7.5, 12.3).

* :meth:`persist_long_term` embeds the entry text through the ``Embedding_Provider`` and
  upserts the vector into the ``Vector_Store`` under an ``ltm:<conversation_id>``
  namespace (the store's ``document_id``), keeping long-term entries disjoint from RAG
  chunks in the same store. The entry's text and metadata are retained in a lightweight
  payload map keyed by the generated entry id, because the ``Vector_Store`` persists only
  vectors and their identifiers.
* :meth:`retrieve_long_term` embeds the query, delegates ranking to
  ``Vector_Store.query`` (which returns ``min(k, count)`` matches ordered by descending
  similarity), and maps the matches back to :class:`MemoryEntry` records in that order,
  returning an empty list when nothing has been stored (Req 7.2-7.4).
"""

from __future__ import annotations

import uuid

from agentforge.embeddings.base import Embedding_Provider
from agentforge.memory.base import MemoryEntry
from agentforge.vectorstore.base import Vector_Store

# Default namespace prefix under which long-term entries are stored so they coexist with
# RAG chunks in the same Vector_Store without collision (Req 7.5).
DEFAULT_LTM_NAMESPACE = "ltm"


class Long_Term_Memory:
    """Persistent, cross-conversation semantic memory over the existing seams."""

    def __init__(
        self,
        embedding_provider: Embedding_Provider,
        vector_store: Vector_Store,
        *,
        namespace_prefix: str = DEFAULT_LTM_NAMESPACE,
    ) -> None:
        self._embeddings = embedding_provider
        self._store = vector_store
        self._namespace_prefix = namespace_prefix
        # entry id -> MemoryEntry payload (text + metadata); the Vector_Store keeps only
        # the vector and its identifier, so the text payload lives here (Req 7.5).
        self._payload: dict[str, MemoryEntry] = {}

    def _namespace(self, metadata: dict) -> str:
        """Return the ``document_id`` namespace for an entry (``ltm:<conversation_id>``)."""
        conversation_id = metadata.get("conversation_id")
        if conversation_id:
            return f"{self._namespace_prefix}:{conversation_id}"
        return self._namespace_prefix

    def persist_long_term(self, text: str, metadata: dict) -> str:
        """Embed ``text`` and upsert it into the Vector_Store; return the entry id (Req 7.1).

        Reuses the existing Embedding_Provider and Vector_Store — no embedding or vector
        storage is reimplemented (Req 7.5).
        """
        metadata = dict(metadata or {})
        entry_id = str(uuid.uuid4())
        embedding = self._embeddings.embed_text(text)
        self._store.upsert(
            chunk_id=entry_id,
            document_id=self._namespace(metadata),
            embedding=embedding,
        )
        self._payload[entry_id] = MemoryEntry(
            id=entry_id, text=text, metadata=metadata
        )
        return entry_id

    def retrieve_long_term(self, query: str, k: int) -> list[MemoryEntry]:
        """Return ``min(k, stored_count)`` entries by descending similarity (Req 7.2-7.4).

        Delegates ranking to ``Vector_Store.query`` and maps the ordered matches back to
        their :class:`MemoryEntry` payloads; returns ``[]`` when ``k <= 0`` or nothing has
        been stored (Req 7.4).
        """
        if k <= 0 or not self._payload:
            return []
        embedding = self._embeddings.embed_text(query)
        matches = self._store.query(embedding, k)
        entries: list[MemoryEntry] = []
        for match in matches:
            entry = self._payload.get(match.chunk_id)
            if entry is not None:
                entries.append(entry)
        return entries
