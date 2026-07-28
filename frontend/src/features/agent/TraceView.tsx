/**
 * `TraceView`: fetches and renders a run's ordered trace (Req 9.5, 9.6, 6.3).
 *
 * Calls `GET /agent/runs/{run_id}/trace` and renders the entries as a
 * `TraceTimeline` ordered by `ordinal`. A `404 not_found` presents the trace as
 * not found (Req 9.6). When the run exists but exposes no trace detail (NoOp
 * tracing), the empty entry list renders as "trace detail unavailable" rather
 * than an error (Req 6.3).
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Skeleton } from "../../components/ui/Skeleton";
import { TraceTimeline, type TraceEntry } from "./TraceTimeline";

interface TraceResponse {
  run_id: string;
  entries?: TraceEntry[];
}

export function TraceView({ runId }: { runId: string }): JSX.Element {
  const { orgId } = useSession();

  const trace = useQuery<TraceResponse, ClientError>({
    queryKey: orgScopedKey(orgId, "agent-trace", runId),
    queryFn: () =>
      runRequest<TraceResponse>(() =>
        apiClient.GET("/agent/runs/{run_id}/trace", {
          params: { path: { run_id: runId } },
        }),
      ),
  });

  if (trace.isLoading) {
    return (
      <div className="flex flex-col gap-2" data-testid="trace-skeleton">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-12 w-full" />
      </div>
    );
  }

  if (trace.isError) {
    if (trace.error.kind === "not_found") {
      return (
        <div data-testid="trace-not-found">
          <EmptyState
            title="Trace not found"
            message="No trace is available for this run."
          />
        </div>
      );
    }
    return <ErrorBanner error={trace.error} onRetry={() => void trace.refetch()} />;
  }

  return <TraceTimeline entries={trace.data?.entries ?? []} />;
}
