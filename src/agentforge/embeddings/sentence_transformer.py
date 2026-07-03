"""SentenceTransformer_Embeddings: default local embedding provider.

Wraps ``sentence-transformers/all-MiniLM-L6-v2`` (384-dimensional), runs on CPU, and
needs **no API key**, satisfying the free-tier promise (Req 14.4). The model is loaded
lazily on first use so importing this module (and constructing the provider) is cheap
and side-effect free. Any failure to generate an embedding raises ``EmbeddingError``
and returns no partial result (Req 9.4).
"""

from __future__ import annotations

from threading import Lock

from agentforge.embeddings.base import Embedding_Provider, EmbeddingError

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_DIMENSION = 384


class SentenceTransformer_Embeddings(Embedding_Provider):
    """Local, CPU-only embedding provider backed by sentence-transformers."""

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        dimension: int = _DEFAULT_DIMENSION,
    ) -> None:
        self._model_name = model
        self._dimension = dimension
        self._model = None  # lazily loaded SentenceTransformer instance
        self._lock = Lock()

    @property
    def dimension(self) -> int:
        return self._dimension

    def _get_model(self):
        """Load the model on first use (thread-safe, CPU device)."""
        if self._model is None:
            with self._lock:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer

                        self._model = SentenceTransformer(
                            self._model_name, device="cpu"
                        )
                    except Exception as exc:  # pragma: no cover - env/model load path
                        raise EmbeddingError(
                            f"Failed to load embedding model '{self._model_name}': {exc}"
                        ) from exc
        return self._model

    def embed_text(self, text: str) -> list[float]:
        """Return a single embedding vector of length ``dimension`` (Req 9.1)."""
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts. Raises EmbeddingError on failure with no partial result."""
        if texts is None:
            raise EmbeddingError("Cannot embed a null input")
        model = self._get_model()
        try:
            raw = model.encode(
                list(texts),
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
            vectors = [[float(v) for v in row] for row in raw]
        except Exception as exc:
            raise EmbeddingError(f"Embedding generation failed: {exc}") from exc

        # Post-condition: every vector matches the configured dimension (Req 9.1).
        for vec in vectors:
            if len(vec) != self._dimension:
                raise EmbeddingError(
                    "Embedding dimension mismatch: expected "
                    f"{self._dimension}, got {len(vec)}"
                )
        return vectors
