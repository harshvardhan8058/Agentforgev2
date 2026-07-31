/**
 * `WebhooksView`: register outbound endpoints, test them, and read their delivery log.
 *
 * The console could already *show* that a run finished; nothing could *tell* another system.
 * This is the surface for that: an endpoint, the events it wants, and — the part that makes it
 * operable rather than merely configurable — the per-endpoint delivery log, because the first
 * question after "I registered a webhook" is invariably "is it working?".
 *
 * Binds only to the shipped contracts, gated on `manage_webhooks` (admin and above):
 *  - `GET    /webhooks`
 *  - `POST   /webhooks`                    — the only response carrying the signing secret
 *  - `PATCH  /webhooks/{id}`               — pause/resume, re-point, re-subscribe
 *  - `DELETE /webhooks/{id}`
 *  - `POST   /webhooks/{id}/test`          — send a signed `webhook.ping` now
 *  - `GET    /webhooks/{id}/deliveries`    — that endpoint's log, newest first
 *
 * Design decisions worth stating:
 *
 *  - **The event checklist is generated from the contract** (`Subscribable_Event` in
 *    `schema.d.ts`). A hardcoded list would silently stop offering newly published events, and
 *    `webhook.ping` — which is not subscribable — could never appear here by construction.
 *  - **The secret is shown once, in place, with copy-to-clipboard**, exactly like an API key
 *    secret, and is never held anywhere else in the client. A visible warning says so, because
 *    a consumer who loses it cannot recover it: there is no rotation endpoint, deliberately.
 *  - **A failed test send is a success, not an error.** The API returns 200 with a `failed`
 *    delivery; the UI shows the status code and the diagnostic, because that is the answer the
 *    operator asked for. Rendering it as an app error would blame the wrong system.
 *  - **Deliveries load on demand**, per endpoint, so opening the page costs one request no
 *    matter how much history exists.
 *  - All management controls sit inside `<Can permission="manage_webhooks">`, so a role without
 *    it gets no controls in the DOM at all — not disabled ones.
 */
import type { JSX } from "react";
import { useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import {
  Check,
  ChevronDown,
  Copy,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  Webhook,
  X,
} from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can, type Permission } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { Can } from "../../components/Can";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
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
type WebhookSubscription = components["schemas"]["WebhookSubscriptionResponse"];
type CreateWebhookResponse = components["schemas"]["CreateWebhookResponse"];
type WebhookDelivery = components["schemas"]["WebhookDeliveryResponse"];

/** The server's `(created_at, delivery_id)` keyset cursor, sent as `before` / `before_id`. */
interface DeliveryCursor {
  before: string;
  before_id: string;
}

/**
 * Every subscribable event, with the plain-language description of when it fires.
 *
 * `Record<SubscribableEvent, string>` over the **generated** union: publishing a new event
 * server-side fails `tsc` here with a missing property rather than quietly leaving it out of
 * the checklist. The same guard the audit log's action map provides, for the same reason.
 */
const EVENT_DESCRIPTIONS: Record<SubscribableEvent, string> = {
  "run.completed": "An agent or multi-agent run produced its result.",
  "run.failed": "A run ended without an accepted result (a limit, or a rejected plan).",
  "document.ingested": "A document finished ingestion into this organization's corpus.",
  "guardrail.blocked": "A guardrail refused an input before it reached a model.",
};

const ALL_EVENTS = Object.keys(EVENT_DESCRIPTIONS) as SubscribableEvent[];

/** How many delivery rows a log panel requests per page. The server caps `limit` at 200. */
const DELIVERY_PAGE_SIZE = 25;

/** One-shot copy control for the signing secret, mirroring the API-key surface. */
function CopySecret({ secret }: { secret: string }): JSX.Element {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  async function copy(): Promise<void> {
    try {
      await navigator.clipboard?.writeText(secret);
      setCopied(true);
      toast({ title: "Signing secret copied", tone: "success" });
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast({ title: "Copy failed — select and copy manually", tone: "danger" });
    }
  }

  return (
    <Button
      type="button"
      variant="secondary"
      size="sm"
      onClick={copy}
      data-testid="copy-webhook-secret"
      aria-label="Copy webhook signing secret"
    >
      {copied ? (
        <Check className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Copy className="h-4 w-4" aria-hidden="true" />
      )}
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}

/**
 * The delivery log for one endpoint. Mounted only when expanded, so it costs nothing closed.
 *
 * Paginated with the server's own `(created_at, delivery_id)` keyset cursor via
 * `useInfiniteQuery`, because the alternative — telling the operator that older history "is
 * reachable through the API's cursor" — ships the server's pagination as a documented dead end
 * on the one screen that needs it. Deliveries are append-only and read newest-first, which is
 * exactly the shape a keyset cursor is correct for: a row inserted mid-read cannot shift a page
 * boundary the way an offset would.
 */
function DeliveryLog({
  orgId,
  webhookId,
}: {
  orgId: string | null;
  webhookId: string;
}): JSX.Element {
  const deliveries = useInfiniteQuery<
    WebhookDelivery[],
    ClientError,
    InfiniteData<WebhookDelivery[]>,
    readonly unknown[],
    DeliveryCursor | null
  >({
    queryKey: orgScopedKey(orgId, "webhook-deliveries", webhookId),
    initialPageParam: null,
    queryFn: ({ pageParam }) =>
      runRequest<WebhookDelivery[]>(() =>
        apiClient.GET("/webhooks/{webhook_id}/deliveries", {
          params: {
            path: { webhook_id: webhookId },
            query: {
              limit: DELIVERY_PAGE_SIZE,
              // Both or neither: the server refuses a half-supplied cursor with a 422, because
              // a timestamp alone cannot separate deliveries fanned out in one burst.
              ...(pageParam
                ? { before: pageParam.before, before_id: pageParam.before_id }
                : {}),
            },
          },
        }),
      ),
    getNextPageParam: (lastPage) => {
      // A short page is the last page; a full one may or may not be, and asking is cheaper than
      // guessing. The cursor is the last row of the page just read.
      if (lastPage.length < DELIVERY_PAGE_SIZE) return null;
      const last = lastPage[lastPage.length - 1];
      return { before: last.created_at, before_id: last.delivery_id };
    },
  });

  const rows = deliveries.data?.pages.flat() ?? [];

  return (
    <div className="flex flex-col gap-3" data-testid={`webhook-deliveries-${webhookId}`}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-text">Recent deliveries</h3>
        <Button
          type="button"
          variant="secondary"
          size="sm"
          data-testid={`refresh-deliveries-${webhookId}`}
          loading={deliveries.isFetching && !deliveries.isFetchingNextPage}
          onClick={() => void deliveries.refetch()}
        >
          <RefreshCw className="h-4 w-4" aria-hidden="true" />
          Refresh
        </Button>
      </div>

      <p className="sr-only" aria-live="polite">
        {deliveries.isFetching
          ? "Loading deliveries"
          : `${rows.length} ${rows.length === 1 ? "delivery" : "deliveries"} shown`}
      </p>

      {deliveries.isError && (
        <ErrorBanner error={deliveries.error} onRetry={() => void deliveries.refetch()} />
      )}

      {deliveries.isLoading && (
        <div className="flex flex-col gap-2" data-testid={`webhook-deliveries-loading-${webhookId}`}>
          <Skeleton className="h-8 w-full" />
          <Skeleton className="h-8 w-full" />
        </div>
      )}

      {!deliveries.isLoading && !deliveries.isError && rows.length === 0 && (
        <p className="text-sm text-text-muted" data-testid={`webhook-deliveries-empty-${webhookId}`}>
          No deliveries yet. Use <strong>Send test</strong> to verify the endpoint before real
          traffic depends on it.
        </p>
      )}

      {rows.length > 0 && (
        // A horizontally scrollable region with no focusable content inside is unreachable
        // by keyboard (axe `scrollable-region-focusable`, WCAG 2.1.1), so the container is
        // itself a focusable, labelled region. The delivery table holds no controls, which
        // is exactly why this is needed here and not on the tables that do.
        <div
          className="overflow-x-auto"
          tabIndex={0}
          role="region"
          aria-label="Recent deliveries"
        >
          <table className="w-full text-sm" data-testid={`webhook-delivery-table-${webhookId}`}>
            <caption className="sr-only">Recent deliveries for this endpoint, newest first</caption>
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
                  Took
                </th>
                <th scope="col" className="px-3 py-2 font-medium">
                  Detail
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((delivery) => (
                <tr
                  key={delivery.delivery_id}
                  className="border-b border-border/60 align-top last:border-0"
                  data-testid={`webhook-delivery-${delivery.delivery_id}`}
                >
                  <td className="whitespace-nowrap px-3 py-2 text-text-muted">
                    <time dateTime={delivery.created_at}>{formatWhen(delivery.created_at)}</time>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs text-text">{delivery.event}</td>
                  <td className="px-3 py-2">
                    <Badge tone={delivery.status === "delivered" ? "success" : "danger"}>
                      {delivery.status}
                      {delivery.response_status !== null &&
                      delivery.response_status !== undefined
                        ? ` ${delivery.response_status}`
                        : ""}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-text-muted">{delivery.attempts}</td>
                  <td className="px-3 py-2 text-text-muted">
                    {delivery.duration_ms === null || delivery.duration_ms === undefined
                      ? "—"
                      : `${delivery.duration_ms} ms`}
                  </td>
                  <td className="px-3 py-2 text-text-muted">
                    {/* A short diagnostic only. The server never stores a response body, so
                        there is nothing here that could echo a tenant's own content. */}
                    {delivery.error ? (
                      <span className="font-mono text-xs">{delivery.error}</span>
                    ) : (
                      <span className="text-text-subtle">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {deliveries.hasNextPage && (
        <div>
          <Button
            type="button"
            variant="secondary"
            size="sm"
            data-testid={`load-older-deliveries-${webhookId}`}
            loading={deliveries.isFetchingNextPage}
            onClick={() => void deliveries.fetchNextPage()}
          >
            Load older deliveries
          </Button>
        </div>
      )}
    </div>
  );
}

export function WebhooksView(): JSX.Element {
  const { orgId, role } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const permitted = role !== null && can(role, MANAGE_WEBHOOKS);

  const [url, setUrl] = useState("");
  const [description, setDescription] = useState("");
  const [selected, setSelected] = useState<SubscribableEvent[]>(["run.completed"]);
  const [createdSecret, setCreatedSecret] = useState<CreateWebhookResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<string, WebhookDelivery>>({});

  const listKey = orgScopedKey(orgId, "webhooks");

  const webhooks = useQuery<WebhookSubscription[], ClientError>({
    queryKey: listKey,
    enabled: permitted,
    queryFn: () =>
      runRequest<WebhookSubscription[]>(() => apiClient.GET("/webhooks", {})),
  });

  const createWebhook = useMutation<CreateWebhookResponse, ClientError, void>({
    mutationFn: () =>
      runRequest<CreateWebhookResponse>(() =>
        apiClient.POST("/webhooks", {
          body: {
            url: url.trim(),
            events: selected,
            ...(description.trim() ? { description: description.trim() } : {}),
          },
        }),
      ),
    onSuccess: (data) => {
      setCreatedSecret(data);
      setUrl("");
      setDescription("");
      setSelected(["run.completed"]);
      toast({ title: "Webhook registered", tone: "success" });
      void queryClient.invalidateQueries({ queryKey: listKey });
    },
  });

  const setActive = useMutation<
    WebhookSubscription,
    ClientError,
    { webhookId: string; active: boolean }
  >({
    mutationFn: ({ webhookId, active }) =>
      runRequest<WebhookSubscription>(() =>
        apiClient.PATCH("/webhooks/{webhook_id}", {
          params: { path: { webhook_id: webhookId } },
          body: { active },
        }),
      ),
    onSuccess: (data) => {
      toast({ title: data.active ? "Webhook resumed" : "Webhook paused", tone: "success" });
      void queryClient.invalidateQueries({ queryKey: listKey });
    },
  });

  const deleteWebhook = useMutation<void, ClientError, string>({
    mutationFn: (webhookId) =>
      runRequest<void>(() =>
        apiClient.DELETE("/webhooks/{webhook_id}", {
          params: { path: { webhook_id: webhookId } },
        }),
      ),
    onSuccess: () => {
      toast({ title: "Webhook deleted", tone: "success" });
      void queryClient.invalidateQueries({ queryKey: listKey });
    },
  });

  const sendTest = useMutation<WebhookDelivery, ClientError, string>({
    mutationFn: (webhookId) =>
      runRequest<WebhookDelivery>(() =>
        apiClient.POST("/webhooks/{webhook_id}/test", {
          params: { path: { webhook_id: webhookId } },
        }),
      ),
    onSuccess: (delivery) => {
      setTested((current) => ({ ...current, [delivery.webhook_id]: delivery }));
      // A refused endpoint is a successful answer to the question asked, so the toast
      // reports the outcome rather than treating it as a client error.
      toast({
        title:
          delivery.status === "delivered"
            ? "Test delivered"
            : `Test failed${delivery.response_status ? ` (${delivery.response_status})` : ""}`,
        tone: delivery.status === "delivered" ? "success" : "danger",
      });
      void queryClient.invalidateQueries({
        queryKey: orgScopedKey(orgId, "webhook-deliveries", delivery.webhook_id),
      });
    },
  });

  function toggleEvent(event: SubscribableEvent): void {
    setSelected((current) =>
      current.includes(event)
        ? current.filter((value) => value !== event)
        : [...current, event],
    );
  }

  if (!permitted) {
    return (
      <div data-testid="webhooks-view">
        <EmptyState
          title="Webhook management unavailable"
          message="Your role does not permit managing this organization's webhooks."
          icon={<Webhook className="h-8 w-8" />}
        />
      </div>
    );
  }

  const rows = webhooks.data ?? [];
  const canSubmit = url.trim().length > 0 && selected.length > 0;

  return (
    <div className="flex flex-col gap-6" data-testid="webhooks-view">
      <PageHeader
        eyebrow="Administration"
        icon={Webhook}
        title="Webhooks"
        description="Send signed events to your own systems when a run finishes, a document is ingested, or a guardrail refuses an input."
      />

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(20rem,26rem)_minmax(0,1fr)]">
        {/* The <h2> keeps the document outline valid: the cards below use <h3> titles, so
            without it the page would jump h1 -> h3 (axe `heading-order`, WCAG 1.3.1). */}
        <section className="flex flex-col gap-3" aria-labelledby="add-webhook-heading">
          <h2
            id="add-webhook-heading"
            className="text-sm font-semibold uppercase tracking-wide text-text-muted"
          >
            Add an endpoint
          </h2>

          <Can permission={MANAGE_WEBHOOKS}>
            <Card>
              <CardHeader>
                <CardTitle>New webhook</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-4">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="webhook-url" className="text-sm font-medium text-text">
                    Endpoint URL
                  </label>
                  <Input
                    id="webhook-url"
                    data-testid="webhook-url-input"
                    type="url"
                    inputMode="url"
                    placeholder="https://hooks.example.com/agentforge"
                    value={url}
                    onChange={(event) => setUrl(event.target.value)}
                    aria-describedby="webhook-url-hint"
                  />
                  <p id="webhook-url-hint" className="text-xs text-text-subtle">
                    Must be an https URL that resolves to a public address. Private, loopback
                    and link-local addresses are refused.
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
                    placeholder="Ops channel"
                    maxLength={200}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                  />
                </div>

                <fieldset className="flex flex-col gap-2">
                  <legend className="text-sm font-medium text-text">Events</legend>
                  {/* The event name is the label; the sentence describing when it fires is a
                      *description*, wired with `aria-describedby` rather than folded into the
                      label — a screen reader should announce "run.completed, checkbox" and
                      then the explanation, not one long run-on name. */}
                  {ALL_EVENTS.map((event) => (
                    <div key={event} className="flex items-start gap-2 text-sm">
                      <input
                        id={`webhook-event-${event}`}
                        data-testid={`webhook-event-${event}`}
                        type="checkbox"
                        className="mt-1 h-4 w-4 rounded border-border text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
                        checked={selected.includes(event)}
                        aria-describedby={`webhook-event-${event}-hint`}
                        onChange={() => toggleEvent(event)}
                      />
                      <span className="flex flex-col">
                        <label
                          htmlFor={`webhook-event-${event}`}
                          className="cursor-pointer font-mono text-xs text-text"
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
                    </div>
                  ))}
                  {selected.length === 0 && (
                    <p className="text-xs text-danger" data-testid="webhook-events-required">
                      Choose at least one event — a webhook that wants nothing would never fire.
                    </p>
                  )}
                </fieldset>

                <Button
                  type="button"
                  data-testid="create-webhook"
                  loading={createWebhook.isPending}
                  disabled={!canSubmit}
                  onClick={() => createWebhook.mutate()}
                >
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  Register webhook
                </Button>
              </CardContent>
            </Card>
          </Can>

          {createWebhook.isError && <ErrorBanner error={createWebhook.error} />}

          {createdSecret && (
            <Card raised data-testid="created-webhook-secret">
              <CardHeader className="flex flex-row items-start justify-between gap-3">
                <CardTitle>Copy your signing secret</CardTitle>
                {/* Dismissable: the secret is unrecoverable, so it stays until the operator
                    says they have it, rather than until they happen to navigate away. */}
                <Button
                  type="button"
                  variant="secondary"
                  size="sm"
                  data-testid="dismiss-webhook-secret"
                  onClick={() => setCreatedSecret(null)}
                >
                  <X className="h-4 w-4" aria-hidden="true" />
                  I have stored it
                </Button>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <p className="text-sm text-text-muted">
                  This secret is shown only once. Store it securely — it cannot be retrieved or
                  rotated, and without it your endpoint cannot verify that a delivery came from
                  AgentForge.
                </p>
                <div className="flex items-center gap-3">
                  <code
                    className="flex-1 truncate rounded-md border border-border bg-bg-subtle px-3 py-2 text-sm"
                    data-testid="webhook-secret-value"
                  >
                    {createdSecret.secret}
                  </code>
                  <CopySecret secret={createdSecret.secret} />
                </div>
                <p className="text-xs text-text-subtle">
                  Each delivery carries{" "}
                  <code>X-AgentForge-Signature: t=&lt;unix&gt;,v1=&lt;hmac&gt;</code>, an
                  HMAC-SHA256 over <code>&quot;&lt;t&gt;.&lt;raw body&gt;&quot;</code>.
                </p>
              </CardContent>
            </Card>
          )}
        </section>

        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="endpoints-heading">
          <h2
            id="endpoints-heading"
            className="text-sm font-semibold uppercase tracking-wide text-text-muted"
          >
            Registered endpoints
          </h2>

          <p className="sr-only" aria-live="polite" data-testid="webhooks-status">
            {webhooks.isFetching
              ? "Loading webhooks"
              : `${rows.length} ${rows.length === 1 ? "webhook" : "webhooks"} registered`}
          </p>

          {webhooks.isError && (
            <ErrorBanner error={webhooks.error} onRetry={() => void webhooks.refetch()} />
          )}

          {webhooks.isLoading && (
            <div className="flex flex-col gap-2" data-testid="webhooks-loading">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}

          {!webhooks.isLoading && !webhooks.isError && rows.length === 0 && (
            <EmptyState
              title="No webhooks yet"
              message="Register an endpoint to have AgentForge notify your systems when a run finishes or a guardrail blocks an input."
              icon={<Webhook className="h-8 w-8" />}
            />
          )}

          {rows.length > 0 && (
            <ul className="flex flex-col gap-3" data-testid="webhooks-list">
              {rows.map((webhook) => {
                const isOpen = expanded === webhook.webhook_id;
                const lastTest = tested[webhook.webhook_id];
                return (
                  <li key={webhook.webhook_id}>
                    <Card data-testid={`webhook-${webhook.webhook_id}`}>
                      <CardContent className="flex flex-col gap-3 py-4">
                        <div className="flex flex-wrap items-center gap-2">
                          <Webhook
                            className="h-4 w-4 shrink-0 text-text-muted"
                            aria-hidden="true"
                          />
                          <code className="min-w-0 break-all text-sm text-text">
                            {webhook.url}
                          </code>
                          {webhook.active ? (
                            <Badge tone="success">active</Badge>
                          ) : (
                            <Badge tone="neutral">paused</Badge>
                          )}
                        </div>

                        {webhook.description && (
                          <p className="text-sm text-text-muted">{webhook.description}</p>
                        )}

                        <div className="flex flex-wrap gap-1.5">
                          {webhook.events.map((event) => (
                            <span
                              key={event}
                              className="rounded bg-bg-subtle px-1.5 py-0.5 font-mono text-[0.7rem] text-text-muted"
                            >
                              {event}
                            </span>
                          ))}
                        </div>

                        <p className="text-xs text-text-subtle">
                          Added <time dateTime={webhook.created_at}>{formatWhen(webhook.created_at)}</time>
                        </p>

                        {lastTest && (
                          <p
                            className="text-xs text-text-muted"
                            data-testid={`webhook-test-result-${webhook.webhook_id}`}
                          >
                            Last test:{" "}
                            <strong>
                              {lastTest.status}
                              {lastTest.response_status ? ` ${lastTest.response_status}` : ""}
                            </strong>
                            {lastTest.error ? ` — ${lastTest.error}` : ""}
                          </p>
                        )}

                        <div className="flex flex-wrap items-center gap-2">
                          <Button
                            type="button"
                            variant="secondary"
                            size="sm"
                            data-testid={`toggle-deliveries-${webhook.webhook_id}`}
                            aria-expanded={isOpen}
                            aria-controls={`deliveries-panel-${webhook.webhook_id}`}
                            onClick={() => setExpanded(isOpen ? null : webhook.webhook_id)}
                          >
                            <ChevronDown
                              className={`h-4 w-4 transition-transform ${isOpen ? "rotate-180" : ""}`}
                              aria-hidden="true"
                            />
                            {isOpen ? "Hide deliveries" : "Deliveries"}
                          </Button>

                          <Can permission={MANAGE_WEBHOOKS}>
                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              data-testid={`send-test-${webhook.webhook_id}`}
                              loading={
                                sendTest.isPending && sendTest.variables === webhook.webhook_id
                              }
                              onClick={() => sendTest.mutate(webhook.webhook_id)}
                            >
                              <Send className="h-4 w-4" aria-hidden="true" />
                              Send test
                            </Button>

                            <Button
                              type="button"
                              variant="secondary"
                              size="sm"
                              data-testid={`toggle-active-${webhook.webhook_id}`}
                              loading={
                                setActive.isPending &&
                                setActive.variables?.webhookId === webhook.webhook_id
                              }
                              onClick={() =>
                                setActive.mutate({
                                  webhookId: webhook.webhook_id,
                                  active: !webhook.active,
                                })
                              }
                            >
                              {webhook.active ? (
                                <Pause className="h-4 w-4" aria-hidden="true" />
                              ) : (
                                <Play className="h-4 w-4" aria-hidden="true" />
                              )}
                              {webhook.active ? "Pause" : "Resume"}
                            </Button>

                            <span className="ml-auto" />

                            <Dialog>
                              <DialogTrigger asChild>
                                <Button
                                  type="button"
                                  variant="danger"
                                  size="sm"
                                  data-testid={`delete-webhook-${webhook.webhook_id}`}
                                >
                                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                                  Delete
                                </Button>
                              </DialogTrigger>
                              <DialogContent
                                title="Delete this webhook?"
                                description="Deliveries stop immediately and this endpoint's delivery history is removed. Registering it again issues a new signing secret."
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
                                      data-testid={`confirm-delete-${webhook.webhook_id}`}
                                      onClick={() => deleteWebhook.mutate(webhook.webhook_id)}
                                    >
                                      Delete webhook
                                    </Button>
                                  </DialogClose>
                                </div>
                              </DialogContent>
                            </Dialog>
                          </Can>
                        </div>

                        {isOpen && (
                          <div
                            id={`deliveries-panel-${webhook.webhook_id}`}
                            className="border-t border-border pt-3"
                          >
                            <DeliveryLog orgId={orgId} webhookId={webhook.webhook_id} />
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </li>
                );
              })}
            </ul>
          )}

          {setActive.isError && <ErrorBanner error={setActive.error} />}
          {deleteWebhook.isError && <ErrorBanner error={deleteWebhook.error} />}
          {sendTest.isError && <ErrorBanner error={sendTest.error} />}
        </section>
      </div>
    </div>
  );
}
