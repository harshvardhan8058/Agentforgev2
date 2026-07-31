/**
 * Canonical dashboard query definitions.
 *
 * `WorkspaceStats` and `GettingStarted` both need the same workspace signals.
 * TanStack Query caches by key, so two components declaring the *same* key with
 * *different* `select`/return shapes will overwrite each other's cache entry —
 * whichever mounts first wins, and the other silently reads a payload missing
 * the fields it expects.
 *
 * Defining each shared query exactly once removes that hazard entirely: one key,
 * one shape, one request. Feature views that already own a key (the prompt
 * registry, evaluations, API keys) are reused verbatim here so their existing
 * `invalidateQueries` calls keep the dashboard fresh for free.
 */
import type { UseQueryOptions } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";

/** All-time usage rollup for the active Org_Context. */
export interface UsageSummary {
  total_tokens: number;
  /** Verbatim decimal string from the backend — never re-derived. */
  total_cost: string;
}

/** Shared defaults: dashboard signals are informational, so never retry. */
const SHARED = { retry: false, staleTime: 30_000 } as const;

export function documentsQuery(
  orgId: string | null,
  enabled: boolean,
): UseQueryOptions<unknown, ClientError> {
  return {
    ...SHARED,
    enabled,
    queryKey: orgScopedKey(orgId, "documents"),
    queryFn: () => runRequest(() => apiClient.GET("/documents")),
  };
}

export function usageSummaryQuery(
  orgId: string | null,
  enabled: boolean,
): UseQueryOptions<UsageSummary, ClientError> {
  return {
    ...SHARED,
    enabled,
    queryKey: orgScopedKey(orgId, "usage-summary"),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/analytics/usage", { params: { query: {} } }),
      );
      return { total_tokens: data.total_tokens, total_cost: data.total_cost };
    },
  };
}

/** Reuses the prompt registry's key so creating a prompt refreshes this too. */
export function promptsQuery(
  orgId: string | null,
  enabled: boolean,
): UseQueryOptions<unknown, ClientError> {
  return {
    ...SHARED,
    enabled,
    queryKey: orgScopedKey(orgId, "prompts"),
    queryFn: () => runRequest(() => apiClient.GET("/prompts")),
  };
}

/** Reuses the evaluations view's key (`eval-datasets`) for the same reason. */
export function datasetsQuery(
  orgId: string | null,
  enabled: boolean,
): UseQueryOptions<unknown, ClientError> {
  return {
    ...SHARED,
    enabled,
    queryKey: orgScopedKey(orgId, "eval-datasets"),
    queryFn: () => runRequest(() => apiClient.GET("/evaluations/datasets")),
  };
}

/** Reuses the API-keys view's key; requires an active org in the path. */
export function apiKeysQuery(
  orgId: string | null,
  enabled: boolean,
): UseQueryOptions<unknown, ClientError> {
  return {
    ...SHARED,
    enabled: enabled && orgId !== null,
    queryKey: orgScopedKey(orgId, "api-keys"),
    queryFn: () =>
      runRequest(() =>
        apiClient.GET("/orgs/{org_id}/api-keys", {
          params: { path: { org_id: orgId as string } },
        }),
      ),
  };
}
