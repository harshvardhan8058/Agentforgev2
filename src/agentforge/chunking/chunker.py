"""Chunker: character-based sliding-window chunker.

Splits document text into bounded, overlapping ``Chunk`` segments.

Guarantees (Req 8.1-8.5):
    * Every chunk's content length is at most ``chunk_max_chars`` (Req 8.1).
    * Consecutive chunks overlap by ``chunk_overlap_chars`` (Req 8.2).
    * Every chunk records its ``document_id`` and ordinal ``index`` (Req 8.3).
    * Input of length <= ``chunk_max_chars`` yields exactly one chunk (Req 8.4).
    * Concatenating chunks in order while removing the recorded per-boundary overlap
      reconstructs the (normalized) input text exactly (Req 8.5).

Markdown handling is governed by ``markdown_mode`` (Req 8.1 design note): ``strip``
normalizes Markdown to plain text before chunking; ``preserve`` keeps the input text
unchanged. The round-trip property is defined against the *normalized* input, so it
holds under both modes.
"""

from __future__ import annotations

import re
import uuid
from html.parser import HTMLParser

import markdown as _markdown

from agentforge.models.domain import Chunk


class _HTMLTextExtractor(HTMLParser):
    """Collect visible text from rendered Markdown HTML, deterministically."""

    _BLOCK_TAGS = {
        "p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
        "pre", "blockquote", "tr", "table", "hr",
    }

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def get_text(self) -> str:
        text = "".join(self._parts)
        # Collapse runs of blank lines and trim trailing whitespace deterministically.
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def normalize_markdown(text: str, markdown_mode: str) -> str:
    """Normalize input text according to ``markdown_mode``.

    ``preserve`` returns the text unchanged; ``strip`` renders Markdown and extracts
    plain text. The transform is a pure, deterministic function of its inputs.
    """
    if markdown_mode == "preserve":
        return text
    if markdown_mode == "strip":
        if not text:
            return ""
        html = _markdown.markdown(text)
        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        return extractor.get_text()
    raise ValueError(f"Unknown markdown_mode: {markdown_mode!r}")


class Chunker:
    """Character-based sliding-window chunker with recorded per-boundary overlap."""

    def __init__(
        self,
        chunk_max_chars: int,
        chunk_overlap_chars: int,
        markdown_mode: str = "preserve",
    ) -> None:
        if chunk_max_chars <= 0:
            raise ValueError("chunk_max_chars must be positive")
        if chunk_overlap_chars < 0:
            raise ValueError("chunk_overlap_chars must be non-negative")
        if chunk_overlap_chars >= chunk_max_chars:
            raise ValueError("chunk_overlap_chars must be < chunk_max_chars")
        self._max = chunk_max_chars
        self._overlap = chunk_overlap_chars
        self._markdown_mode = markdown_mode

    def normalize(self, text: str) -> str:
        """Return the chunker-input text after markdown normalization."""
        return normalize_markdown(text, self._markdown_mode)

    def chunk(self, text: str, document_id: str) -> list[Chunk]:
        """Split ``text`` into ordered, overlapping chunks for ``document_id``."""
        normalized = self.normalize(text)
        n = len(normalized)
        step = self._max - self._overlap  # guaranteed >= 1 by constructor checks

        # Req 8.4: input at most max size -> exactly one chunk.
        if n <= self._max:
            return [
                Chunk(
                    id=self._new_id(),
                    document_id=document_id,
                    index=0,
                    content=normalized,
                    overlap_prev=0,
                )
            ]

        chunks: list[Chunk] = []
        start = 0
        index = 0
        prev_end = 0
        while True:
            end = min(start + self._max, n)
            overlap_prev = 0 if index == 0 else (prev_end - start)
            chunks.append(
                Chunk(
                    id=self._new_id(),
                    document_id=document_id,
                    index=index,
                    content=normalized[start:end],
                    overlap_prev=overlap_prev,
                )
            )
            if end == n:
                break
            prev_end = end
            start += step
            index += 1
        return chunks

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())
