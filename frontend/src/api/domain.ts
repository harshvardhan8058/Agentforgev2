/**
 * Hand-written client-side domain types shared across the pure logic layer.
 *
 * Server-facing request/response types are GENERATED into `schema.d.ts`; these
 * are the small, stable domain shapes the pure logic (reducers, citation
 * mapping) operate on, mirroring the backend `CitationModel`.
 */

/** A `{ document_id, chunk_id }` pair identifying a grounded answer's source. */
export interface Citation {
  document_id: string;
  chunk_id: string;
}
