"""Domain models for AgentForge.

These are plain, framework-agnostic dataclasses shared across the service and
persistence layers. They intentionally do not depend on FastAPI, SQLAlchemy, or
any provider implementation so the core logic stays decoupled from transport and
infrastructure concerns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Document:
    """A source document submitted for ingestion."""

    id: str
    filename: str
    content_type: str  # text/plain | application/pdf | text/markdown
    size_bytes: int
    status: str  # "ingested" | "rejected"
    created_at: datetime
    # Hex SHA-256 of the uploaded bytes, used to recognise a re-upload of the same file.
    # Identifies *content*, so the same file uploaded under two names is one document.
    # Optional and defaulted: documents ingested before content hashing have no hash (the
    # raw bytes are not retained, so it cannot be backfilled) and are never matched.
    content_hash: str | None = None


@dataclass
class Chunk:
    """A bounded segment of a document's text produced by the Chunker."""

    id: str
    document_id: str
    index: int  # ordinal position within the document
    content: str
    overlap_prev: int = 0  # overlap chars shared with the previous chunk


@dataclass
class Embedding:
    """A fixed-length numeric vector representation of a Chunk."""

    chunk_id: str
    document_id: str
    vector: list[float]  # length == configured embedding_dimension


@dataclass
class Citation:
    """A reference identifying the document and chunk supporting an answer."""

    document_id: str
    chunk_id: str


@dataclass
class Grounded_Answer:
    """An answer derived from retrieved Chunks, accompanied by Citations."""

    text: str
    citations: list[Citation] = field(default_factory=list)
    provider: str = ""
    grounded: bool = True  # False only in the no-context case
