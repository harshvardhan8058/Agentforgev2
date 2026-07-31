/**
 * `RecentMultiAgentRuns`: the org's recent Planner → Researcher → Writer → Critic runs.
 *
 * A run could only be fetched by an id the caller already held, so a finished
 * collaboration was unreachable once its id left the screen. `GET /multi-agent/runs` was
 * added for exactly this.
 *
 * Rows lead with the task, because that is what identifies a run to a person; the id is a
 * generated UUID. Selecting one hands its id to the parent, which shows the persisted
 * result — so a past run can be reopened rather than only re-run.
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { History } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge, type BadgeTone } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import { formatWhen } from "../../lib/formatWhen";

interface MultiAgentRunSummary {
  run_id: string;
  conversation_id: string;
  task: string;
  status: string;
  termination_reason?: string | null;
  created_at: string;
}

/** Status colour: a run still awaiting a person is the one worth noticing. */
const STATUS_TONE: Record<string, BadgeTone> = {
  running: "info",
  awaiting_approval: "warning",
  terminated: "neutral",
};

export function RecentMultiAgentRuns({
  selectedRunId,
  onSelect,
}: {
  selectedRunId?: string | null;
  onSelect: (runId: string) => void;
}): JSX.Element {
  const { orgId } = useSession();

  const runs = useQuery<MultiAgentRunSummary[], ClientError>({
    queryKey: orgScopedKey(orgId, "multi-agent-runs"),
    queryFn: () =>
      runRequest<MultiAgentRunSummary[]>(() => apiClient.GET("/multi-agent/runs")),
  });

  const rows = runs.data ?? [];

  return (
    <Card data-testid="recent-multi-runs-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <History className="h-4 w-4 text-text-muted" aria-hidden="true" />
          Recent runs
        </CardTitle>
      </CardHeader>
      <CardContent>
        {runs.isLoading && (
          <div className="flex flex-col gap-2" data-testid="multi-runs-skeleton">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}

        {runs.isError && (
          <ErrorBanner error={runs.error} onRetry={() => void runs.refetch()} />
        )}

        {runs.data && rows.length === 0 && (
          <div data-testid="multi-runs-empty">
            <EmptyState
              title="No runs yet"
              message="Runs you start appear here, and their result stays available afterwards."
              icon={<History className="h-8 w-8" />}
            />
          </div>
        )}

        {rows.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="multi-runs-list">
            {rows.map((row) => (
              <li key={row.run_id}>
                <button
                  type="button"
                  aria-pressed={selectedRunId === row.run_id}
                  data-testid={`multi-run-row-${row.run_id}`}
                  onClick={() => onSelect(row.run_id)}
                  className={cn(
                    "flex w-full flex-col gap-1 rounded-lg border px-3 py-2.5 text-left transition-colors",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
                    selectedRunId === row.run_id
                      ? "border-primary/60 bg-primary-subtle"
                      : "border-border bg-surface hover:border-border-strong",
                  )}
                >
                  {/* The task, not the id. */}
                  <span className="truncate text-sm font-medium text-text">
                    {row.task}
                  </span>
                  <span className="flex flex-wrap items-center gap-2">
                    <Badge tone={STATUS_TONE[row.status] ?? "neutral"}>
                      {row.status.replace(/_/g, " ")}
                    </Badge>
                    {row.termination_reason && (
                      <Badge tone="neutral">{row.termination_reason}</Badge>
                    )}
                    <span className="text-xs text-text-subtle">
                      {formatWhen(row.created_at)}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
