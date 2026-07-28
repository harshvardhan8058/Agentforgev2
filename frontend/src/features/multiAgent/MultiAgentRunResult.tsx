/**
 * `MultiAgentRunResult`: the persisted run result view (Req 10.6, 10.7).
 *
 * Calls `GET /multi-agent/runs/{run_id}` and renders the `status`,
 * `termination_reason`, final output + citations, and the role-attributed
 * ordered trace (via the shared `TraceTimeline`). A `404 not_found` presents
 * the run as not found (Req 10.7). Used both as an on-demand lookup and as the
 * refresh target after a `409` on approval (Req 10.8).
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import type { Citation } from "../../api/domain";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Markdown } from "../../components/markdown/Markdown";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { TraceTimeline, type TraceEntry } from "../agent/TraceTimeline";

interface FinalOutput {
  content: string;
  citations?: Citation[];
}

interface MultiAgentRunResultData {
  run_id: string;
  status: "running" | "awaiting_approval" | "terminated";
  termination_reason?: string | null;
  final_output?: FinalOutput | null;
  trace?: TraceEntry[];
}

export function MultiAgentRunResult({
  runId,
  /** A monotonically-increasing token; bump it to force a refetch. */
  refreshToken = 0,
}: {
  runId: string;
  refreshToken?: number;
}): JSX.Element {
  const { orgId } = useSession();

  const result = useQuery<MultiAgentRunResultData, ClientError>({
    queryKey: orgScopedKey(orgId, "multi-agent-run", runId, refreshToken),
    queryFn: () =>
      runRequest<MultiAgentRunResultData>(() =>
        apiClient.GET("/multi-agent/runs/{run_id}", {
          params: { path: { run_id: runId } },
        }),
      ),
  });

  if (result.isLoading) {
    return (
      <div className="flex flex-col gap-2" data-testid="multi-result-skeleton">
        <Skeleton className="h-6 w-1/3" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  if (result.isError) {
    if (result.error.kind === "not_found") {
      return (
        <div data-testid="multi-result-not-found">
          <EmptyState
            title="Run not found"
            message="This run does not exist or is not available in your organization."
          />
        </div>
      );
    }
    return (
      <ErrorBanner error={result.error} onRetry={() => void result.refetch()} />
    );
  }

  const data = result.data;
  const citations = data?.final_output?.citations ?? [];

  return (
    <div className="flex flex-col gap-4" data-testid="multi-result">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="info" data-testid="multi-result-status">
          {data?.status}
        </Badge>
        {data?.termination_reason && (
          <Badge tone="neutral" data-testid="multi-result-termination-reason">
            {data.termination_reason}
          </Badge>
        )}
      </div>

      {data?.final_output && (
        <Card data-testid="multi-result-output">
          <CardHeader>
            <CardTitle>Final output</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <Markdown content={data.final_output.content} citations={citations} />
            {citations.length > 0 && (
              <ul className="flex flex-col gap-1" data-testid="multi-result-citations">
                {citations.map((c, i) => (
                  <li
                    key={`${c.document_id}-${c.chunk_id}-${i}`}
                    id={`citation-${i + 1}`}
                    className="flex flex-wrap items-center gap-2 text-sm text-text-muted"
                  >
                    <Badge tone="primary">[{i + 1}]</Badge>
                    <span className="font-mono text-xs">{c.document_id}</span>
                    <span aria-hidden="true">·</span>
                    <span className="font-mono text-xs">{c.chunk_id}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <Card data-testid="multi-result-trace">
        <CardHeader>
          <CardTitle>Trace</CardTitle>
        </CardHeader>
        <CardContent>
          <TraceTimeline entries={data?.trace ?? []} />
        </CardContent>
      </Card>
    </div>
  );
}
