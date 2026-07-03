"""Documents router: ``GET /documents`` and ``DELETE /documents/{id}`` — Task 13.3.

* ``GET /documents`` returns a summary of every stored document (id, filename, content
  type, size, status, chunk count, created-at).
* ``DELETE /documents/{document_id}`` removes the document and cascades the deletion to
  its chunks (relational ``ON DELETE CASCADE``) and to its embeddings in the vector
  store (``Vector_Store.delete_document``). An unknown id returns ``404 not_found``;
  a successful delete returns ``204``.

The synchronous store/vector-store calls run in a worker thread so the event loop is
never blocked.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from fastapi.concurrency import run_in_threadpool

from agentforge.api.deps import get_document_store, get_vector_store
from agentforge.api.errors import AppError
from agentforge.api.schemas import DocumentSummary
from agentforge.storage.base import DocumentStore
from agentforge.vectorstore.base import Vector_Store

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentSummary])
async def list_documents(
    store: DocumentStore = Depends(get_document_store),
) -> list[DocumentSummary]:
    """Return a summary of all stored documents."""
    listings = await run_in_threadpool(store.list_documents)
    return [
        DocumentSummary(
            document_id=item.document_id,
            filename=item.filename,
            content_type=item.content_type,
            size_bytes=item.size_bytes,
            status=item.status,
            chunk_count=item.chunk_count,
            created_at=item.created_at,
        )
        for item in listings
    ]


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    store: DocumentStore = Depends(get_document_store),
    vector_store: Vector_Store = Depends(get_vector_store),
) -> Response:
    """Delete a document and cascade to its chunks and embeddings."""
    existing = await run_in_threadpool(store.get_document, document_id)
    if existing is None:
        raise AppError(
            "not_found",
            f"Document {document_id!r} was not found.",
            status.HTTP_404_NOT_FOUND,
        )

    # Cascade: relational rows (documents -> chunks) and vector-store embeddings.
    await run_in_threadpool(store.delete_document, document_id)
    await run_in_threadpool(vector_store.delete_document, document_id)

    return Response(status_code=status.HTTP_204_NO_CONTENT)
