/**
 * `WebhooksView`: register outbound webhook endpoints and see what was delivered.
 *
 * The console half of the notification seam. Binds to the `/webhooks` contract:
 *  - `GET    /webhooks`                      — the org's subscriptions
 *  - `POST   /webhooks`                      — register one (returns the secret **once**)
 *  - `PATCH  /webhooks/{id}`                 — pause, resume, repoint, re-subscribe
 *  - `DELETE /webhooks/{id}`                 — remove it and its delivery log
 *  - `POST   /webhooks/{id}/test`            — send a `webhook.ping` and report the result
 *  - `GET    /webhooks/{id}/deliveries`      — the delivery log, newest first, keyset-paged
 *
 * Design decisions this screen commits to:
 *
 *  - **The secret is shown once, and the UI says so.** It appears in a copyable panel after
 *    registration and is dismissible; nothing here can fetch it again, because no endpoint
 *    can. Pretending otherwise (a "reveal" affordance) would be a lie about the API.
 *  - **The event checklist is generated from the contract** (`Subscribable_Event` in
 *    `schema.d.ts`), so it cannot offer an event the server does not emit or miss one it
 *    added. `Record<SubscribableEvent, string>` over the generated union means adding an
 *    event server-side fails `tsc` here rather than silently dropping a checkbox.
 *  - **A failed delivery is data, not an error.** A red banner is for *our* failures; a
 *    tenant's endpoint returning 500 is information their operator needs, so it is rendered
 *    as a status in the log.
 *  - **Server validation is surfaced verbatim.** The SSRF admission rules (https, no
 *    credentials in the URL, must resolve publicly) are not re-implemented here — a second
 *    implementation would eventually disagree with the first — so the server's 400 message
 *    is what the operator reads.
 */
import type { JSX } from "react";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  Pause,
  Play,
  Plus,
  Radio,
  Send,
  ShieldCheck,
  Trash2,
  XCircle,
} from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can, type Permission } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { CopyableId } from "../../components/ui/CopyableId";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogTrigger,
} from "../../components/ui/Dialog";
import { Input } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatWhen } from "../../lib/formatWhen";
import type { components } from "../../api/schema";

const MANAGE_WEBHOOKS: Permission = "manage_webhooks";

type SubscribableEvent = components["schemas"]["Subscribable_Event"];
type Webhook = components["schemas"]["WebhookSubscriptionResponse"];
type CreatedWebhook = components["schemas"]["CreateWebhookResponse"];
type Delivery = components["schemas"]["WebhookDeliveryResponse"];

/**
 * What each subscribable event means, in the operator's terms.
 *
 * `Record<SubscribableEvent, string>` over the **generated** union is what keeps this from
 * drifting: a new event on the server fails the typecheck here with a missing property,
 * rather than quietly never appearing in the checklist.
 */
const EVENT_DESCRIPTIONS: Record<SubscribableEvent, string> = {
  "run.completed": "An agent or multi-agent run produced a result.",
  "run.failed": "A run ended without producing an accepted result.",
  "document.ingested": "A document finished ingestion.",
  "guardrail.blocked": "An input guardrail refused a request.",
  "budget.threshold_crossed": "This organization crossed a spend-budget threshold.",
};

const ALL_EVENTS = Object.keys(EVENT_DESCRIPTIONS) as SubscribableEvent[];

/** Matches the server's default page size for the delivery log. */
const DELIVERY_PAGE_SIZE = 25;

function eventTone(event: string): "primary" | "warning" | "danger" | "info" {
  if (event === "run.failed") return "danger";
  if (event === "guardrail.blocked" || event === "budget.threshold_crossed") {
    return "warning";
  }
  if (event === "webhook.ping") return "info";
  return "primary";
}

export function WebhooksView(): JSX.Element {
  const { orgId, role } = useSession();
  const permitted = role !== null && can(role, MANAGE_WEBHOOKS);
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const listKey = orgScopedKey(orgId, "webhooks");

  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<SubscribableEvent[]>(["run.completed"]);
  const [createdSecret, setCreatedSecret] = useState<CreatedWebhook | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const webhooks = useQuery<Webhook[], ClientError>({
    queryKey: listKey,
    enabled: permitted,
    queryFn: () => runRequest<Webhook[]>(() => apiClient.GET("/webhooks")),
  });

  function refresh(): void {
    void queryClient.invalidateQueries({ queryKey: listKey });
  }

  const create = useMutation<CreatedWebhook, ClientError, void>({
    mutationFn: () =>
      runRequest<CreatedWebhook>(() =>
        apiClient.POST("/webhooks", {
          body: {
            url: url.trim(),
            events: selected,
            // Registered active: the point of registering is to receive events, and pausing
            // is one click away on the row afterwards.
            active: true,
            ...(description.trim() ? { description: description.trim() } : {}),
          },
        }),
      ),
    onSuccess: (created) => {
      // Held in state, not in a toast: the secret cannot be retrieved again, so it must not
      // disappear on a timer while the operator is copying it.
      setCreatedSecret(created);
      toast({
        title: "Webhook registered",
        description: "Copy the signing secret now — it is shown once.",
        tone: "success",
      });
      setUrl("");
      setDescription("");
      setSelected(["run.completed"]);
      refresh();
    },
  });

  const update = useMutation<
    Webhook,
    ClientError,
    { webhook: Webhook; body: Record<string, unknown> }
  >({
    mutationFn: ({ webhook, body }) =>
      runRequest<Webhook>(() =>
        apiClient.PATCH("/webhooks/{webhook_id}", {
          params: { path: { webhook_id: webhook.webhook_id } },
          body: body as never,
        }),
      ),
    onSuccess: (updated) => {
      toast({
        title: updated.active ? "Webhook resumed" : "Webhook paused",
        description: updated.url,
        tone: "success",
      });
      refresh();
    },
  });

  const remove = useMutation<void, ClientError, Webhook>({
    mutationFn: (webhook) =>
      runRequest<void>(() =>
        apiClient.DELETE("/webhooks/{webhook_id}", {
          params: { path: { webhook_id: webhook.webhook_id } },
        }),
      ),
    onSuccess: (_data, webhook) => {
      toast({
        title: "Webhook removed",
        description: webhook.url,
        tone: "success",
      });
      if (expanded === webhook.webhook_id) setExpanded(null);
      if (createdSecret?.webhook.webhook_id === webhook.webhook_id) setCreatedSecret(null);
      refresh();
    },
  });

  const sendTest = useMutation<Delivery, ClientError, Webhook>({
    mutationFn: (webhook) =>
      runRequest<Delivery>(() =>
        apiClient.POST("/webhooks/{webhook_id}/test", {
          params: { path: { webhook_id: webhook.webhook_id } },
        }),
      ),
    onSuccess: (delivery, webhook) => {
      // A non-2xx from the endpoint is reported as a *result*, not as an error: the request
      // succeeded, and what failed is information the operator asked for.
      toast({
        title:
          delivery.status === "delivered"
            ? "Test delivery succeeded"
            : "Test delivery failed",
        description:
          delivery.status === "delivered"
            ? `HTTP ${delivery.response_status ?? 200} in ${delivery.duration_ms} ms`
            : (delivery.error ?? "The endpoint could not be reached."),
        // `danger` for a failed delivery rather than `success`: the request worked, but the
        // answer is bad news and must not be styled as an achievement.
        tone: delivery.status === "delivered" ? "success" : "danger",
      });
      void queryClient.invalidateQueries({
        queryKey: orgScopedKey(orgId, "webhook-deliveries", webhook.webhook_id),
      });
    },
  });

  function toggleEvent(event: SubscribableEvent): void {
    setSelected((current) =>
      current.includes(event)
        ? current.filter((e) => e !== event)
        : [...current, event],
    );
  }

  if (!permitted) {
    return (
      <div data-testid="webhooks-view">
        <PageHeader
          eyebrow="Administration"
          icon={Radio}
          title="Webhooks"
          description="Outbound notifications for runs, ingestion, guardrails, and spend."
        />
        <EmptyState
          title="Webhooks unavailable"
          message="Your role does not permit managing this organization's webhooks."
          icon={<ShieldCheck className="h-8 w-8" />}
        />
      </div>
    );
  }

  const rows = webhooks.data ?? [];

  return (
    <div className="flex flex-col gap-6" data-testid="webhooks-view">
      <PageHeader
        eyebrow="Administration"
        icon={Radio}
        title="Webhooks"
        description="Register an HTTPS endpoint and AgentForge will POST a signed event when a run finishes, a document is ingested, a guardrail blocks a request, or this organization crosses a spend threshold."
      />

      {createdSecret && (
        <Card data-testid="webhook-secret-panel">
          <CardHeader>
            <CardTitle as="h2" className="flex items-center gap-2 text-base">
              <CheckCircle2 className="h-4 w-4 text-success" aria-hidden="true" />
              Signing secret
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {/* Assertive, not polite: this is the only time this value exists on screen. */}
            <p className="text-sm text-text-muted" role="alert">
              Copy this now. It is shown once and cannot be retrieved again — every delivery
              is signed with it, and a consumer verifies the{" "}
              <code>X-AgentForge-Signature</code> header against it.
            </p>
            {/* `full`: a secret shown once must be readable in its entirety, in case the
                clipboard is unavailable (a console served over plain HTTP). */}
            <CopyableId
              value={createdSecret.secret}
              label="webhook signing secret"
              testId="webhook-secret"
              full
            />
            <div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                data-testid="dismiss-webhook-secret"
                onClick={() => setCreatedSecret(null)}
              >
                I have stored it
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card data-testid="register-webhook-card">
        <CardHeader>
          <CardTitle as="h2" className="flex items-center gap-2 text-base">
            <Plus className="h-4 w-4 text-text-muted" aria-hidden="true" />
            Register an endpoint
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="webhook-url" className="text-sm font-medium text-text">
                Endpoint URL
              </label>
              <Input
                id="webhook-url"
                data-testid="webhook-url-input"
                type="url"
                inputMode="url"
                autoComplete="off"
                placeholder="https://hooks.example.com/agentforge"
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                aria-describedby="webhook-url-hint"
              />
              <p id="webhook-url-hint" className="text-xs text-text-subtle">
                HTTPS only, and the host must resolve to a public address. Redirects are not
                followed.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="webhook-description"
                className="text-sm font-medium text-text"
              >
                Description <span className="text-text-subtle">(optional)</span>
              </label>
              <Input
                id="webhook-description"
                data-testid="webhook-description-input"
                maxLength={200}
                placeholder="Ops alerting channel"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </div>
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="text-sm font-medium text-text">Events</legend>
            <ul className="flex flex-col gap-2" data-testid="webhook-event-checklist">
              {ALL_EVENTS.map((event) => (
                <li key={event} className="flex items-start gap-2">
                  <input
                    id={`webhook-event-${event}`}
                    data-testid={`webhook-event-${event}`}
                    type="checkbox"
                    className="mt-1 h-4 w-4 rounded border-border text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                    checked={selected.includes(event)}
                    onChange={() => toggleEvent(event)}
                    aria-describedby={`webhook-event-${event}-hint`}
                  />
                  <span className="flex flex-col">
                    <label
                      htmlFor={`webhook-event-${event}`}
                      className="font-mono text-sm text-text"
                    >
                      {event}
                    </label>
                    <span
                      id={`webhook-event-${event}-hint`}
                      className="text-xs text-text-subtle"
                    >
                      {EVENT_DESCRIPTIONS[event]}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          </fieldset>

          <div>
            <Button
              type="button"
              data-testid="create-webhook"
              loading={create.isPending}
              disabled={url.trim() === "" || selected.length === 0}
              onClick={() => create.mutate()}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Register webhook
            </Button>
          </div>
          {selected.length === 0 && (
            <p className="text-xs text-warning" data-testid="webhook-no-events-hint">
              Select at least one event: a subscription that hears about nothing would never
              be called.
            </p>
          )}
          {create.isError && <ErrorBanner error={create.error} />}
        </CardContent>
      </Card>

      <p className="sr-only" aria-live="polite" data-testid="webhooks-status">
        {webhooks.isFetching
          ? "Loading webhooks"
          : `${rows.length} ${rows.length === 1 ? "webhook" : "webhooks"} registered`}
      </p>

      {webhooks.isError && (
        <ErrorBanner error={webhooks.error} onRetry={() => void webhooks.refetch()} />
      )}

      {webhooks.isLoading && (
        <div className="flex flex-col gap-2" data-testid="webhooks-skeleton">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {!webhooks.isLoading && !webhooks.isError && rows.length === 0 && (
        <EmptyState
          title="No webhooks registered"
          message="Register an endpoint above and AgentForge will POST a signed event to it when something happens."
          icon={<Radio className="h-8 w-8" />}
        />
      )}

      {rows.length > 0 && (
        <ul className="flex flex-col gap-3" data-testid="webhooks-list">
          {rows.map((webhook) => (
            <li key={webhook.webhook_id}>
              <Card data-testid={`webhook-${webhook.webhook_id}`}>
                <CardContent className="flex flex-col gap-3 pt-6">
                  <div className="flex flex-wrap items-start gap-2">
                    <div className="flex min-w-0 flex-col gap-1">
                      <span className="break-all font-mono text-sm text-text">
                        {webhook.url}
                      </span>
                      {webhook.description && (
                        <span className="text-sm text-text-muted">
                          {webhook.description}
                        </span>
                      )}
                      <span className="text-xs text-text-subtle">
                        Registered{" "}
                        <time dateTime={webhook.created_at}>
                          {formatWhen(webhook.created_at)}
                        </time>
                      </span>
                    </div>
                    <Badge
                      tone={webhook.active ? "success" : "neutral"}
                      data-testid={`webhook-state-${webhook.webhook_id}`}
                    >
                      {webhook.active ? "Active" : "Paused"}
                    </Badge>
                  </div>

                  <ul className="flex flex-wrap gap-1.5">
                    {webhook.events.map((event) => (
                      <li key={event}>
                        <Badge tone={eventTone(event)}>{event}</Badge>
                      </li>
                    ))}
                  </ul>

                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      data-testid={`test-webhook-${webhook.webhook_id}`}
                      loading={
                        sendTest.isPending &&
                        sendTest.variables?.webhook_id === webhook.webhook_id
                      }
                      onClick={() => sendTest.mutate(webhook)}
                    >
                      <Send className="h-4 w-4" aria-hidden="true" />
                      Send test
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      data-testid={`toggle-webhook-${webhook.webhook_id}`}
                      loading={
                        update.isPending &&
                        update.variables?.webhook.webhook_id === webhook.webhook_id
                      }
                      onClick={() =>
                        update.mutate({ webhook, body: { active: !webhook.active } })
                      }
                    >
                      {webhook.active ? (
                        <Pause className="h-4 w-4" aria-hidden="true" />
                      ) : (
                        <Play className="h-4 w-4" aria-hidden="true" />
                      )}
                      {webhook.active ? "Pause" : "Resume"}
                    </Button>
                    <Button
                      type="button"
                      variant="secondary"
                      size="sm"
                      data-testid={`deliveries-webhook-${webhook.webhook_id}`}
                      aria-expanded={expanded === webhook.webhook_id}
                      onClick={() =>
                        setExpanded(
                          expanded === webhook.webhook_id ? null : webhook.webhook_id,
                        )
                      }
                    >
                      {expanded === webhook.webhook_id
                        ? "Hide deliveries"
                        : "Recent deliveries"}
                    </Button>
                    <Dialog>
                      <DialogTrigger asChild>
                        <Button
                          type="button"
                          variant="danger"
                          size="sm"
                          data-testid={`remove-webhook-${webhook.webhook_id}`}
                        >
                          <Trash2 className="h-4 w-4" aria-hidden="true" />
                          Remove
                        </Button>
                      </DialogTrigger>
                      <DialogContent
                        title="Remove this webhook?"
                        description={`${webhook.url} stops receiving events, and its delivery history is deleted. The signing secret cannot be recovered, so re-registering means updating the consumer with a new one.`}
                      >
                        <div className="flex justify-end gap-2">
                          <DialogClose asChild>
                            <Button type="button" variant="secondary" size="sm">
                              Cancel
                            </Button>
                          </DialogClose>
                          <DialogClose asChild>
                            <Button
                              type="button"
                              variant="danger"
                              size="sm"
                              data-testid={`confirm-remove-webhook-${webhook.webhook_id}`}
                              onClick={() => remove.mutate(webhook)}
                            >
                              Remove webhook
                            </Button>
                          </DialogClose>
                        </div>
                      </DialogContent>
                    </Dialog>
                  </div>

                  {expanded === webhook.webhook_id && (
                    <DeliveryLog orgId={orgId} webhookId={webhook.webhook_id} />
                  )}
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}

      {update.isError && <ErrorBanner error={update.error} />}
      {remove.isError && <ErrorBanner error={remove.error} />}
      {/* A transport-level failure of the test request itself (not a failed delivery, which
          is reported as a result). */}
      {sendTest.isError && <ErrorBanner error={sendTest.error} />}
    </div>
  );
}

/**
 * The delivery log for one subscription: newest first, paged with the server's keyset cursor.
 *
 * Paging is real rather than a "use the API" note, because the log is where an operator lands
 * when a consumer has been failing for a while — and the interesting rows are then always
 * older than the first page.
 */
function DeliveryLog({
  orgId,
  webhookId,
}: {
  orgId: string | null;
  webhookId: string;
}): JSX.Element {
  // Each page's cursor, so "load older" is additive rather than replacing the view.
  const [pages, setPages] = useState<Delivery[][]>([]);
  const [cursor, setCursor] = useState<{ before: string; beforeId: string } | null>(null);

  const first = useQuery<Delivery[], ClientError>({
    queryKey: orgScopedKey(orgId, "webhook-deliveries", webhookId),
    queryFn: () =>
      runRequest<Delivery[]>(() =>
        apiClient.GET("/webhooks/{webhook_id}/deliveries", {
          params: {
            path: { webhook_id: webhookId },
            query: { limit: DELIVERY_PAGE_SIZE },
          },
        }),
      ),
  });

  const older = useMutation<Delivery[], ClientError, { before: string; beforeId: string }>({
    mutationFn: (position) =>
      runRequest<Delivery[]>(() =>
        apiClient.GET("/webhooks/{webhook_id}/deliveries", {
          params: {
            path: { webhook_id: webhookId },
            query: {
              limit: DELIVERY_PAGE_SIZE,
              before: position.before,
              before_id: position.beforeId,
            },
          },
        }),
      ),
    onSuccess: (page) => {
      if (page.length > 0) setPages((current) => [...current, page]);
      const last = page.at(-1);
      setCursor(
        page.length === DELIVERY_PAGE_SIZE && last
          ? { before: last.created_at, beforeId: last.delivery_id }
          : null,
      );
    },
  });

  const firstPage = first.data ?? [];
  const rows = [...firstPage, ...pages.flat()];
  const lastRow = rows.at(-1);
  const nextCursor =
    cursor ??
    (firstPage.length === DELIVERY_PAGE_SIZE && lastRow
      ? { before: lastRow.created_at, beforeId: lastRow.delivery_id }
      : null);

  return (
    <div
      className="flex flex-col gap-2 border-t border-border pt-3"
      data-testid={`deliveries-${webhookId}`}
    >
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-medium text-text">Recent deliveries</h3>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="ml-auto"
          data-testid={`refresh-deliveries-${webhookId}`}
          loading={first.isFetching}
          onClick={() => {
            setPages([]);
            setCursor(null);
            void first.refetch();
          }}
        >
          Refresh
        </Button>
      </div>

      {first.isError && (
        <ErrorBanner error={first.error} onRetry={() => void first.refetch()} />
      )}

      {first.isLoading && (
        <Skeleton className="h-16 w-full" data-testid={`deliveries-skeleton-${webhookId}`} />
      )}

      {!first.isLoading && !first.isError && rows.length === 0 && (
        <p className="text-sm text-text-subtle" data-testid={`deliveries-empty-${webhookId}`}>
          Nothing delivered yet. Send a test to check the endpoint before real events depend
          on it.
        </p>
      )}

      {rows.length > 0 && (
        /* Focusable and labelled so the horizontal scroll is reachable by keyboard, which a
           plain overflow container is not. */
        <div
          className="overflow-x-auto"
          tabIndex={0}
          role="group"
          aria-label="Webhook delivery history"
        >
          <table className="w-full text-sm" data-testid={`deliveries-table-${webhookId}`}>
            <caption className="sr-only">
              Webhook deliveries for this endpoint, newest first
            </caption>
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-subtle">
                <th scope="col" className="px-3 py-2 font-medium">
                  When
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Event
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Result
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Attempts
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Endpoint time
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((delivery) => (
                <tr
                  key={delivery.delivery_id}
                  className="border-b border-border/60 align-top last:border-0"
                  data-testid={`delivery-${delivery.delivery_id}`}
                >
                  <td className="whitespace-nowrap px-3 py-2 text-text-muted">
                    <time dateTime={delivery.created_at}>
                      {formatWhen(delivery.created_at)}
                    </time>
                  </td>
                  <td className="px-3 py-2">
                    <Badge tone={eventTone(delivery.event)}>{delivery.event}</Badge>
                  </td>
                  <td className="px-3 py-2">
                    {delivery.status === "delivered" ? (
                      <span className="flex items-center gap-1.5 text-text">
                        <CheckCircle2
                          className="h-4 w-4 text-success"
                          aria-hidden="true"
                        />
                        HTTP {delivery.response_status ?? 200}
                      </span>
                    ) : (
                      <span className="flex flex-col gap-0.5">
                        <span className="flex items-center gap-1.5 text-text">
                          <XCircle className="h-4 w-4 text-danger" aria-hidden="true" />
                          {delivery.response_status
                            ? `HTTP ${delivery.response_status}`
                            : "Not reached"}
                        </span>
                        {delivery.error && (
                          <span className="break-all text-xs text-text-subtle">
                            {delivery.error}
                          </span>
                        )}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-text-muted">{delivery.attempts}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-text-muted">
                    {delivery.duration_ms} ms
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {older.isError && <ErrorBanner error={older.error} />}

      {nextCursor && (
        <div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid={`load-older-deliveries-${webhookId}`}
            loading={older.isPending}
            onClick={() => older.mutate(nextCursor)}
          >
            Load older deliveries
          </Button>
        </div>
      )}
    </div>
  );
}
