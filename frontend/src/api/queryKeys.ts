/**
 * The React Query cache-key convention (Req 4.6).
 *
 * Every server-state query is keyed by `[resource, orgId, ...params]` so that
 * switching the active Org_Context (adopting the stored token whose `org_id`
 * matches the selection) re-scopes every displayed list/detail by cache key and
 * re-fetches under the new context. Feature views MUST build their query keys
 * through `orgScopedKey` so the org dimension is never accidentally omitted.
 *
 * Establishing this convention here (rather than inline in each feature) keeps
 * the org-scoping guarantee in one place, mirroring the backend's org-scoped
 * data access.
 */

/** A single, serializable query-key parameter segment. */
export type KeyParam = string | number | boolean | null | undefined;

/**
 * Build an org-scoped React Query key: `[resource, orgId, ...params]`.
 *
 * `orgId` is included as the second segment so a change of Org_Context yields a
 * distinct key and TanStack Query re-fetches under the new context. When there
 * is no active Org_Context the `orgId` segment is `null`, which still produces a
 * stable, distinct key from any real org.
 */
export function orgScopedKey(
  orgId: string | null,
  resource: string,
  ...params: readonly KeyParam[]
): readonly [string, string | null, ...KeyParam[]] {
  return [resource, orgId, ...params] as const;
}
