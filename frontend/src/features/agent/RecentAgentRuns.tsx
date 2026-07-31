/**
 * `RecentAgentRuns`: the org's recent single-agent runs.
 *
 * A trace could only be fetched by a run id the caller already held, so a finished run
 * was unreachable the moment its id left the screen — the page could start runs but never
 * show one that had happened. `GET /agent/runs` was added for exactly this.
 *
 * Selecting a row surfaces that run's trace in place, via the same `TraceView` the live
 * path uses, so the reasoning of a past run is inspectable rather than merely listed.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { CopyableId } from "../../components/ui/CopyableId";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import { formatWhen } from "../../lib/formatWhen";
import { TraceView } from "./TraceView";

interface AgentRunSummary {
  run_id: string;
  created_at: string;
  step_count: number;
  tool_call_count: number;
}

export function RecentAgentRuns(): JSX.Element {
  const { orgId } = useSession();
  const [openRunId, setOpenRunId] = useState<string | null>(null);

  const runs = useQuery<AgentRunSummary[], ClientError>({
    queryKey: orgScopedKey(orgId, "agent-runs"),
    queryFn: () => runRequest<AgentRunSummary[]>(() => apiClient.GET("/agent/runs")),
  });

  const rows = runs.data ?? [];

  return (
    <Card data-testid="recent-agent-runs-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4 text-text-muted" aria-hidden="true" />
          Recent runs
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {runs.isLoading && (
          <div className="flex flex-col gap-2" data-testid="agent-runs-skeleton">
            <Skeleton className="h-11 w-full" />
            <Skeleton className="h-11 w-full" />
          </div>
        )}

        {runs.isError && (
          <ErrorBanner error={runs.error} onRetry={() => void runs.refetch()} />
        )}

        {runs.data && rows.length === 0 && (
          <div data-testid="agent-runs-empty">
            <EmptyState
              title="No runs yet"
              message="Runs you start appear here, and their reasoning stays inspectable afterwards."
              icon={<History className="h-8 w-8" />}
            />
          </div>
        )}

        {rows.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="agent-runs-list">
            {rows.map((row) => {
              const open = openRunId === row.run_id;
              return (
                <li key={row.run_id} className="flex flex-col gap-2">
                  <button
                    type="button"
                    aria-expanded={open}
                    data-testid={`agent-run-row-${row.run_id}`}
                    onClick={() => setOpenRunId(open ? null : row.run_id)}
                    className={cn(
                      "flex flex-col gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors",
                      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
                      open
                        ? "border-primary/60 bg-primary-subtle"
                        : "border-border bg-surface hover:border-border-strong",
                    )}
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <Badge tone="neutral">
                        {row.step_count} step{row.step_count === 1 ? "" : "s"}
                      </Badge>
                      {row.tool_call_count > 0 && (
                        <Badge tone="info">
                          {row.tool_call_count} tool call
                          {row.tool_call_count === 1 ? "" : "s"}
                        </Badge>
                      )}
                      <span className="text-xs text-text-subtle">
                        {formatWhen(row.created_at)}
                      </span>
                    </span>
                    <span className="text-xs text-text-muted">
                      {open ? "Hide trace" : "Show trace"}
                    </span>
                  </button>

                  {open && (
                    <div
                      className="rounded-lg border border-border bg-bg-subtle p-3"
                      data-testid={`agent-run-trace-${row.run_id}`}
                    >
                      {/* The run id is needed for API calls and support, so it is
                          copyable rather than printed in full. */}
                      <div className="mb-2">
                        <CopyableId value={row.run_id} label="run id" />
                      </div>
                      <TraceView runId={row.run_id} />
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
