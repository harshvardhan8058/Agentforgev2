"""Text extraction for supported document formats (Req 7.1, 7.2).

Supports plain text, PDF, and Markdown. Each extractor takes raw bytes and returns the
extracted text. Markdown extraction applies ``markdown_mode`` normalization by
delegating to the shared normalizer in the Chunker module, so the same strip/preserve
behavior is used everywhere. Extraction failures raise ``ExtractionError`` which the
Ingestion_Service maps to the ``extraction_failure`` response.
"""

from __future__ import annotations

import io

import pypdf

from agentforge.chunking.chunker import normalize_markdown

# Supported content types (the ingestion allow-list, Req 7.5).
CONTENT_TYPE_TEXT = "text/plain"
CONTENT_TYPE_PDF = "application/pdf"
CONTENT_TYPE_MARKDOWN = "text/markdown"

SUPPORTED_CONTENT_TYPES = frozenset(
    {CONTENT_TYPE_TEXT, CONTENT_TYPE_PDF, CONTENT_TYPE_MARKDOWN}
)


class ExtractionError(RuntimeError):
    """Raised when a supported-format document cannot be read (Req 7.6)."""


def extract_text(data: bytes) -> str:
    """Extract text from a plain-text document."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"Could not decode text document: {exc}") from exc


def extract_pdf(data: bytes) -> str:
    """Extract text from a PDF document using pypdf."""
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        parts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:  # pypdf raises various errors on corrupt input
        raise ExtractionError(f"Could not read PDF document: {exc}") from exc
    return "\n".join(parts)


def extract_markdown(data: bytes, markdown_mode: str = "strip") -> str:
    """Extract text from a Markdown document, applying markdown_mode (Req 7.1)."""
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ExtractionError(f"Could not decode markdown document: {exc}") from exc
    return normalize_markdown(raw, markdown_mode)


def extract(content_type: str, data: bytes, markdown_mode: str = "strip") -> str:
    """Dispatch extraction by content type. Raises ExtractionError on read failure.

    The caller is responsible for enforcing the supported-format allow-list before
    invoking this function.
    """
    if content_type == CONTENT_TYPE_TEXT:
        return extract_text(data)
    if content_type == CONTENT_TYPE_PDF:
        return extract_pdf(data)
    if content_type == CONTENT_TYPE_MARKDOWN:
        return extract_markdown(data, markdown_mode)
    raise ExtractionError(f"No extractor for content type: {content_type!r}")
