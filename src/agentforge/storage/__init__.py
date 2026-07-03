"""Document storage adapters (relational document/chunk bookkeeping).

Provides the ``DocumentStore`` port used by the Ingestion_Service (as a
``DocumentSink``), the Retriever (as a ``Chunk_Text_Source``), and the documents
router (list / get / delete). Two implementations are available: an in-memory store
for keyless standalone runs and tests, and a DB-backed adapter for production.
"""
