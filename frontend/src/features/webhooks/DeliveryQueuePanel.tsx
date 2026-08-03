/**
 * `DeliveryQueuePanel`: what has not arrived yet, and what gave up trying.
 *
 * The operator-facing half of durable delivery. Before the outbox there was nothing to render
 * here — a failed webhook was a log line the tenant could not read — so "my endpoint was down for
 * an hour, did I lose those events?" had no answer. Now it does, and the answer is actionable.
 *
 * Binds to `GET /webhooks/queue` and `POST /webhooks/queue/{entry_id}/redeliver`.
 *
 * Two deliberate choices:
 *
 *  - **Delivered events are not shown here.** They are in each subscription's delivery log. Two
 *    surfaces answering "did it arrive" would eventually disagree.
 *  - **A pending entry has no Redeliver button.** It is already scheduled, and offering the button
 *    would invite an operator to duplicate an event that was going to arrive anyway. The server
 *    refuses it with a `409`; the UI simply does not ask.
 */
import type { JSX } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlarmClock, CheckCircle2, RefreshCw, RotateCcw } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useToast } from "../../hooks/useToast";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatWhen } from "../../lib/formatWhen";
import type { components } from "../../api/schema";

type QueueSummary = components["schemas"]["WebhookQueueSummaryResponse"];
type QueueEntry = components["schemas"]["WebhookQueueEntryResponse"];

export function DeliveryQueuePanel({ orgId }: { orgId: string | null }): JSX.Element {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const queueKey = orgScopedKey(orgId, "webhook-queue");

  const queue = useQuery<QueueSummary, ClientError>({
    queryKey: queueKey,
    queryFn: () =>
      runRequest<QueueSummary>(() =>
        apiClient.GET("/webhooks/queue", { params: { query: { limit: 25 } } }),
      ),
  });

  const redeliver = useMutation<QueueEntry, ClientError, QueueEntry>({
    mutationFn: (entry) =>
      runRequest<QueueEntry>(() =>
        apiClient.POST("/webhooks/queue/{entry_id}/redeliver", {
          params: { path: { entry_id: entry.entry_id } },
        }),
      ),
    onSuccess: (entry) => {
      toast({
        title: "Queued for redelivery",
        description: `${entry.event} will be attempted again shortly.`,
        tone: "success",
      });
      void queryClient.invalidateQueries({ queryKey: queueKey });
    },
  });

  const summary = queue.data;
  const entries = summary?.entries ?? [];
  const outstanding = (summary?.pending ?? 0) + (summary?.abandoned ?? 0);

  return (
    <Card data-testid="webhook-queue-panel">
      <CardHeader className="flex flex-row items-center justify-between gap-2">
        <CardTitle as="h2" className="flex items-center gap-2 text-base">
          <AlarmClock className="h-4 w-4 text-text-muted" aria-hidden="true" />
          Delivery queue
        </CardTitle>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          data-testid="refresh-webhook-queue"
          loading={queue.isFetching}
          onClick={() => void queue.refetch()}
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Refresh
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm text-text-muted">
          Events are written down before they are sent, so a consumer that is down does not lose
          them — delivery is retried on an expanding schedule for about a day. Anything that gives
          up waits here for you.
        </p>

        <p className="sr-only" aria-live="polite" data-testid="webhook-queue-status">
          {queue.isFetching
            ? "Loading the delivery queue"
            : `${summary?.pending ?? 0} waiting, ${summary?.abandoned ?? 0} gave up`}
        </p>

        {queue.isError && (
          <ErrorBanner error={queue.error} onRetry={() => void queue.refetch()} />
        )}

        {queue.isLoading && (
          <Skeleton className="h-16 w-full" data-testid="webhook-queue-skeleton" />
        )}

        {!queue.isLoading && !queue.isError && (
          <div className="flex flex-wrap gap-2" data-testid="webhook-queue-counts">
            <Badge tone={(summary?.pending ?? 0) > 0 ? "info" : "neutral"}>
              {summary?.pending ?? 0} waiting
            </Badge>
            <Badge tone={(summary?.abandoned ?? 0) > 0 ? "danger" : "neutral"}>
              {summary?.abandoned ?? 0} gave up
            </Badge>
          </div>
        )}

        {!queue.isLoading && !queue.isError && outstanding === 0 && (
          <p
            className="flex items-center gap-2 text-sm text-text-subtle"
            data-testid="webhook-queue-empty"
          >
            <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
            Everything has been delivered.
          </p>
        )}

        {entries.length > 0 && (
          /* Focusable and labelled so the horizontal scroll is reachable by keyboard, which a
             plain overflow container is not. */
          <div
            className="overflow-x-auto"
            tabIndex={0}
            role="group"
            aria-label="Webhook delivery queue"
          >
            <table className="w-full text-sm" data-testid="webhook-queue-table">
              <caption className="sr-only">
                Webhook events awaiting delivery or abandoned, newest first
              </caption>
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-subtle">
                  <th scope="col" className="px-3 py-2 font-medium">
                    Event
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    State
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Attempts
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Next attempt
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    Last error
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr
                    key={entry.entry_id}
                    className="border-b border-border/60 align-top last:border-0"
                    data-testid={`queue-entry-${entry.entry_id}`}
                  >
                    <td className="px-3 py-2">
                      <Badge tone="primary">{entry.event}</Badge>
                    </td>
                    <td className="px-3 py-2">
                      <Badge tone={entry.status === "abandoned" ? "danger" : "info"}>
                        {entry.status === "abandoned" ? "Gave up" : "Waiting"}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-text-muted">{entry.attempts}</td>
                    <td className="whitespace-nowrap px-3 py-2 text-text-muted">
                      {entry.status === "abandoned" ? (
                        <span className="text-text-subtle">—</span>
                      ) : (
                        <time dateTime={entry.next_attempt_at}>
                          {formatWhen(entry.next_attempt_at)}
                        </time>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {entry.last_error ? (
                        <span className="break-all text-xs text-text-subtle">
                          {entry.last_error}
                        </span>
                      ) : (
                        <span className="text-text-subtle">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {/* Only an abandoned entry: a pending one is already scheduled, and the
                          server refuses a redelivery of it with a 409. */}
                      {entry.status === "abandoned" && (
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          data-testid={`redeliver-${entry.entry_id}`}
                          loading={
                            redeliver.isPending &&
                            redeliver.variables?.entry_id === entry.entry_id
                          }
                          onClick={() => redeliver.mutate(entry)}
                        >
                          <RotateCcw className="h-4 w-4" aria-hidden="true" />
                          Redeliver
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {redeliver.isError && <ErrorBanner error={redeliver.error} />}
      </CardContent>
    </Card>
  );
}
