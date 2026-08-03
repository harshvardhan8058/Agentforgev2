/**
 * `AuditLogView`: the organization's administrative audit trail.
 *
 * Answers the question no other surface could: **who changed this, and when**. Usage
 * analytics say what a run cost and traces say what an agent did; this says that
 * `owner@acme.com` removed a member at 14:02, and that an API key was revoked
 * ten minutes later.
 *
 * Binds to `GET /audit-events` (`read_audit_log`, granted from `admin` upwards) with the
 * filters the server supports: action, actor, and a time window. The action options are
 * **generated from the contract** (`AuditAction` in `schema.d.ts`), so the vocabulary
 * cannot drift from the server's — a hardcoded list would silently stop offering newly
 * audited actions.
 *
 * Reading conventions the design commits to:
 *  - Newest first, because the question is nearly always "what changed recently".
 *  - An actor with no resolvable email (an API key, or a user since deleted) is rendered
 *    as such rather than hidden: the event still happened, and dropping it would make the
 *    trail lie by omission.
 *  - While a filter change is in flight the previous rows stay on screen (fast feedback)
 *    with `aria-busy` set, rather than flashing a skeleton.
 *  - `metadata` is rendered as plain key/value chips. It holds non-secret scalars only,
 *    so there is nothing to expand, redact, or truncate for safety.
 */
import type { JSX } from "react";
import { useMemo, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ScrollText, ShieldCheck } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can, type Permission } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent } from "../../components/ui/Card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSelectTrigger,
} from "../../components/ui/DropdownMenu";
import { PageHeader } from "../../components/ui/PageHeader";
import { Skeleton } from "../../components/ui/Skeleton";
import { formatWhen } from "../../lib/formatWhen";
import type { components } from "../../api/schema";

const READ_AUDIT_LOG: Permission = "read_audit_log";

/** The server's action vocabulary, straight from the generated contract. */
type AuditAction = components["schemas"]["Audit_Action"];
type AuditEvent = components["schemas"]["AuditEventResponse"];

/** Page sizes offered; the server caps `limit` at 200. */
const PAGE_SIZES = [25, 50, 100, 200] as const;
const MAX_PAGE_SIZE = 200;

/**
 * Every action the contract declares, with its label and whether it took something away.
 *
 * `Record<AuditAction, …>` over the **generated** union is what keeps this honest: adding an
 * action server-side fails `tsc` here with a missing property, rather than silently dropping
 * a filter option. Both facts live in ONE map for the same reason — a separate
 * "destructive" list accepted a partial set, so the next `*.deleted` action would have
 * rendered as benign on the one screen whose job is to make removals scannable.
 */
const ACTION_META: Record<AuditAction, { label: string; destructive: boolean }> = {
  "org.created": { label: "Organization created", destructive: false },
  "member.added": { label: "Member added", destructive: false },
  "member.role_changed": { label: "Member role changed", destructive: false },
  "member.removed": { label: "Member removed", destructive: true },
  "team.created": { label: "Team created", destructive: false },
  "team.deleted": { label: "Team deleted", destructive: true },
  "team_member.added": { label: "Added to team", destructive: false },
  "team_member.removed": { label: "Removed from team", destructive: true },
  "api_key.created": { label: "API key created", destructive: false },
  "budget.set": { label: "Spend budget set", destructive: false },
  "budget.removed": { label: "Spend budget removed", destructive: true },
  "api_key.revoked": { label: "API key revoked", destructive: true },
  "integration_connection.created": {
    label: "Connector settings created",
    destructive: false,
  },
  "integration_connection.updated": {
    label: "Connector settings updated",
    destructive: false,
  },
  "integration_connection.deleted": {
    label: "Connector settings removed",
    destructive: true,
  },
  "webhook.created": { label: "Webhook registered", destructive: false },
  "webhook.updated": { label: "Webhook updated", destructive: false },
  "webhook.deleted": { label: "Webhook removed", destructive: true },
};

const ALL_ACTIONS = Object.keys(ACTION_META) as AuditAction[];

/** Label for an action, falling back to the raw value if a stale bundle sees a new one. */
function actionLabel(action: AuditAction): string {
  return ACTION_META[action]?.label ?? action;
}

function actorLabel(event: AuditEvent): string {
  if (event.actor_email) return event.actor_email;
  if (event.actor_kind === "api_key") {
    // A key has no display name; its id is what identifies it in the trail.
    return `API key ${(event.actor_id ?? "").slice(0, 8) || "unknown"}`;
  }
  // A user who has since been deleted. Said plainly, not silently attributed to nobody.
  return "Deleted user";
}

export function AuditLogView(): JSX.Element {
  const { orgId, role } = useSession();
  const permitted = role !== null && can(role, READ_AUDIT_LOG);

  const [action, setAction] = useState<AuditAction | null>(null);
  const [limit, setLimit] = useState<number>(50);

  // `action` and `limit` are part of the key so a filter change is a distinct cache entry;
  // `keepPreviousData` keeps the table on screen while the next page loads instead of
  // flashing the skeleton, which is what makes filtering feel immediate.
  const events = useQuery<AuditEvent[], ClientError>({
    queryKey: orgScopedKey(orgId, "audit-events", `${action ?? "all"}:${limit}`),
    enabled: permitted,
    placeholderData: keepPreviousData,
    queryFn: () =>
      runRequest<AuditEvent[]>(() =>
        apiClient.GET("/audit-events", {
          params: {
            query: {
              limit,
              ...(action ? { action: [action] } : {}),
            },
          },
        }),
      ),
  });

  const rows = useMemo(() => events.data ?? [], [events.data]);

  if (!permitted) {
    return (
      <div data-testid="audit-view">
        <EmptyState
          title="Audit log unavailable"
          message="Your role does not permit reading this organization's audit log."
          icon={<ShieldCheck className="h-8 w-8" />}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6" data-testid="audit-view">
      <PageHeader
        eyebrow="Administration"
        icon={ScrollText}
        title="Audit log"
        description="Every administrative change in this organization, newest first. Append-only: entries are never edited or removed."
      />

      <div className="flex flex-wrap items-end gap-3" data-testid="audit-filters">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="audit-action" className="text-sm font-medium text-text">
            Action
          </label>
          <DropdownMenu>
            <DropdownMenuSelectTrigger
              id="audit-action"
              data-testid="audit-action-trigger"
              className="w-64"
              aria-label="Filter by action"
              value={action ? actionLabel(action) : "All actions"}
            />
            <DropdownMenuContent className="max-h-80 overflow-y-auto">
              <DropdownMenuItem
                data-testid="audit-action-all"
                onSelect={() => setAction(null)}
              >
                All actions
              </DropdownMenuItem>
              {ALL_ACTIONS.map((value) => (
                <DropdownMenuItem
                  key={value}
                  data-testid={`audit-action-${value}`}
                  onSelect={() => setAction(value)}
                >
                  {actionLabel(value)}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <div className="flex flex-col gap-1.5">
          <label htmlFor="audit-limit" className="text-sm font-medium text-text">
            Show
          </label>
          <DropdownMenu>
            <DropdownMenuSelectTrigger
              id="audit-limit"
              data-testid="audit-limit-trigger"
              className="w-32"
              aria-label="Entries per page"
              value={`${limit} entries`}
            />
            <DropdownMenuContent>
              {PAGE_SIZES.map((size) => (
                <DropdownMenuItem
                  key={size}
                  data-testid={`audit-limit-${size}`}
                  onSelect={() => setLimit(size)}
                >
                  {size} entries
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        <Button
          type="button"
          variant="secondary"
          data-testid="audit-refresh"
          loading={events.isFetching}
          onClick={() => void events.refetch()}
        >
          Refresh
        </Button>
      </div>

      {/* The table is replaced asynchronously; without a live region a screen reader is
          told nothing when a filter change or refresh lands. Polite, and only the count,
          so it never competes with the table the user is already reading. */}
      <p className="sr-only" aria-live="polite" data-testid="audit-status">
        {events.isFetching
          ? "Loading audit entries"
          : `${rows.length} audit ${rows.length === 1 ? "entry" : "entries"} shown`}
      </p>

      {events.isError && (
        <ErrorBanner error={events.error} onRetry={() => void events.refetch()} />
      )}

      {events.isLoading && (
        <div className="flex flex-col gap-2" data-testid="audit-skeleton">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-12 w-full" />
        </div>
      )}

      {!events.isLoading && !events.isError && rows.length === 0 && (
        <EmptyState
          title={action ? "No matching entries" : "No administrative activity yet"}
          message={
            action
              ? "No audit entries match this filter. Try a different action or widen the range."
              : "Adding a member, creating a team, or issuing an API key will appear here."
          }
          icon={<ScrollText className="h-8 w-8" />}
        />
      )}

      {rows.length > 0 && (
        <Card>
          <CardContent className="overflow-x-auto p-0">
            {/* `aria-busy` while a filter switch is in flight: `keepPreviousData` keeps the
                previous filter's rows on screen (which is what makes filtering feel
                immediate), so the table must say that it is not yet the new answer. */}
            <table
              className="w-full text-sm"
              data-testid="audit-table"
              aria-busy={events.isPlaceholderData || undefined}
            >
              <caption className="sr-only">
                Administrative audit entries for this organization, newest first
              </caption>
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-subtle">
                  <th scope="col" className="px-4 py-3 font-medium">
                    When
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Action
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Actor
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Target
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    Details
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((event) => {
                  const entries = Object.entries(event.metadata ?? {}).filter(
                    ([, value]) => value !== null && value !== "",
                  );
                  return (
                    <tr
                      key={event.id}
                      className="border-b border-border/60 last:border-0 align-top"
                      data-testid={`audit-row-${event.id}`}
                    >
                      <td className="whitespace-nowrap px-4 py-3 text-text-muted">
                        <time dateTime={event.created_at}>
                          {formatWhen(event.created_at)}
                        </time>
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          tone={
                            ACTION_META[event.action]?.destructive ? "danger" : "primary"
                          }
                        >
                          {actionLabel(event.action)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-text">{actorLabel(event)}</td>
                      <td className="px-4 py-3 text-text-muted">
                        <span className="capitalize">
                          {event.target_type.replace(/_/g, " ")}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {entries.length === 0 ? (
                          <span className="text-text-subtle">—</span>
                        ) : (
                          <span className="flex flex-wrap gap-1.5">
                            {entries.map(([key, value]) => (
                              <span
                                key={key}
                                className="rounded bg-bg-subtle px-1.5 py-0.5 font-mono text-[0.7rem] text-text-muted"
                              >
                                {key}: {String(value)}
                              </span>
                            ))}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {rows.length === limit && limit < MAX_PAGE_SIZE && (
        <p className="text-xs text-text-subtle" data-testid="audit-page-hint">
          Showing the most recent {limit} entries. Increase the page size to see more.
        </p>
      )}
      {rows.length === MAX_PAGE_SIZE && (
        <p className="text-xs text-text-subtle" data-testid="audit-page-max">
          Showing the most recent {MAX_PAGE_SIZE} entries, the largest page this endpoint
          returns. Older history is reachable through the API&apos;s <code>before</code> /{" "}
          <code>before_id</code> cursor.
        </p>
      )}
    </div>
  );
}
