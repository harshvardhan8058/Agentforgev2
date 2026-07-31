/**
 * `BudgetCard`: this organization's monthly spend ceiling, and where it stands.
 *
 * The dashboard could show what had been spent and nothing could limit it. This is the
 * control half: `GET /budget` for the standing (readable by anyone with `read` — someone
 * about to be refused should be able to see why), and `PUT`/`DELETE` behind
 * `manage_budget`, which is owner-only because a spend limit is a financial control.
 *
 * Three states the copy deliberately keeps distinct, because conflating them either alarms
 * or misleads:
 *  - **no budget** — unlimited, the default. Not the same as a budget of `0`.
 *  - **over budget, warning** — reported, traffic continues.
 *  - **over budget, blocking** — new runs are being refused right now, and the card says so
 *    prominently, since that is an active incident for whoever is using the platform.
 *
 * Every monetary value is a string from the server and is rendered **verbatim**: a cost of
 * `0.00013` does not survive a float round trip, and this card sits next to totals that
 * follow the same rule.
 */
import type { JSX } from "react";
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ShieldAlert, Wallet } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can, type Permission } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { useToast } from "../../hooks/useToast";
import { Can } from "../../components/Can";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSelectTrigger,
} from "../../components/ui/DropdownMenu";
import { Input } from "../../components/ui/Input";
import { Skeleton } from "../../components/ui/Skeleton";
import type { components } from "../../api/schema";

const MANAGE_BUDGET: Permission = "manage_budget";

type BudgetStatus = components["schemas"]["BudgetStatusResponse"];
type BudgetAction = NonNullable<BudgetStatus["action"]>;

const ACTION_LABELS: Record<BudgetAction, string> = {
  warn: "Warn only",
  block: "Block new runs",
};

/** Clamp for the bar only; the numeric percentage is still shown verbatim beside it. */
function barWidth(percentUsed: string | null | undefined): number {
  const value = Number(percentUsed ?? 0);
  if (!Number.isFinite(value) || value <= 0) return 0;
  return Math.min(100, value);
}

export function BudgetCard(): JSX.Element {
  const { orgId, role } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const canManage = role !== null && can(role, MANAGE_BUDGET);

  const key = orgScopedKey(orgId, "budget");
  const budget = useQuery<BudgetStatus, ClientError>({
    queryKey: key,
    queryFn: () => runRequest<BudgetStatus>(() => apiClient.GET("/budget", {})),
  });

  const [limit, setLimit] = useState("");
  const [action, setAction] = useState<BudgetAction>("warn");

  // Seed the form from the server once a budget is known, so "edit" starts from the current
  // value rather than from an empty field the owner would have to retype.
  const serverLimit = budget.data?.limit_amount ?? null;
  const serverAction = budget.data?.action ?? null;
  useEffect(() => {
    if (serverLimit !== null) setLimit(serverLimit);
    if (serverAction !== null) setAction(serverAction);
  }, [serverLimit, serverAction]);

  function refresh(): void {
    void queryClient.invalidateQueries({ queryKey: key });
  }

  const save = useMutation<BudgetStatus, ClientError, void>({
    mutationFn: () =>
      runRequest<BudgetStatus>(() =>
        apiClient.PUT("/budget", { body: { limit_amount: limit.trim(), action } }),
      ),
    onSuccess: (updated) => {
      toast({
        title: "Budget saved",
        description: `${updated.limit_amount} per month · ${ACTION_LABELS[action]}`,
        tone: "success",
      });
      refresh();
    },
  });

  const clear = useMutation<void, ClientError, void>({
    mutationFn: () => runRequest<void>(() => apiClient.DELETE("/budget", {})),
    onSuccess: () => {
      toast({ title: "Budget removed", description: "Spend is unlimited again", tone: "success" });
      setLimit("");
      refresh();
    },
  });

  const status = budget.data;
  const hasBudget = status?.limit_amount != null;

  return (
    <Card data-testid="budget-card">
      <CardHeader className="flex flex-row items-center justify-between gap-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Wallet className="h-4 w-4 text-text-muted" aria-hidden="true" />
          Monthly spend budget
        </CardTitle>
        {hasBudget && (
          <Badge tone={status?.blocked ? "danger" : status?.exceeded ? "warning" : "primary"}>
            {status?.blocked
              ? "Blocking new runs"
              : status?.exceeded
                ? "Over budget"
                : ACTION_LABELS[status?.action ?? "warn"]}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {budget.isError && (
          <ErrorBanner error={budget.error} onRetry={() => void budget.refetch()} />
        )}

        {budget.isLoading && <Skeleton className="h-24 w-full" data-testid="budget-skeleton" />}

        {status && (
          <>
            {/* The blocking state is an active incident for every user of this org, so it is
                stated before the numbers rather than inferred from them. */}
            {status.blocked && (
              <p
                className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger/10 p-3 text-sm text-text"
                data-testid="budget-blocked-notice"
                role="alert"
              >
                <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
                <span>
                  New runs are being refused until the period resets or the budget is raised.
                  Reading data is unaffected.
                </span>
              </p>
            )}

            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div>
                <p className="text-xs uppercase tracking-wide text-text-subtle">Spent</p>
                <p className="tabular-nums text-lg text-text" data-testid="budget-spent">
                  {status.spent}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-text-subtle">Budget</p>
                <p className="tabular-nums text-lg text-text" data-testid="budget-limit">
                  {status.limit_amount ?? "No limit"}
                </p>
              </div>
              <div>
                <p className="text-xs uppercase tracking-wide text-text-subtle">Remaining</p>
                <p className="tabular-nums text-lg text-text" data-testid="budget-remaining">
                  {status.remaining ?? "—"}
                </p>
              </div>
            </div>

            {hasBudget && (
              <div className="flex flex-col gap-1.5">
                {/* A native progress element: it carries its own semantics and value, so a
                    screen reader gets the number without a parallel aria-label to maintain. */}
                <progress
                  className="h-2 w-full overflow-hidden rounded-full [&::-webkit-progress-bar]:bg-bg-subtle [&::-webkit-progress-value]:bg-primary"
                  data-testid="budget-progress"
                  value={barWidth(status.percent_used)}
                  max={100}
                >
                  {status.percent_used}%
                </progress>
                <p className="text-xs text-text-muted">
                  <span data-testid="budget-percent">{status.percent_used}</span>% of the
                  budget used this period. Resets{" "}
                  <time dateTime={status.period_end}>
                    {new Date(status.period_end).toLocaleDateString()}
                  </time>
                  .
                </p>
              </div>
            )}

            {!hasBudget && (
              <p className="text-sm text-text-muted" data-testid="budget-unlimited">
                No budget is set, so spend is unlimited.
                {canManage
                  ? " Set one to be warned — or to have new runs refused — when it is reached."
                  : " An owner can set one for this organization."}
              </p>
            )}
          </>
        )}

        <Can permission={MANAGE_BUDGET}>
          <div className="flex flex-wrap items-end gap-3 border-t border-border pt-4">
            <div className="flex flex-col gap-1.5">
              <label htmlFor="budget-limit-input" className="text-sm font-medium text-text">
                Monthly limit
              </label>
              <Input
                id="budget-limit-input"
                data-testid="budget-limit-input"
                className="w-36"
                inputMode="decimal"
                placeholder="100.00"
                value={limit}
                onChange={(e) => setLimit(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="budget-action" className="text-sm font-medium text-text">
                At the limit
              </label>
              <DropdownMenu>
                <DropdownMenuSelectTrigger
                  id="budget-action"
                  aria-label="Action at the limit"
                  data-testid="budget-action-trigger"
                  className="w-44"
                  value={ACTION_LABELS[action]}
                />
                <DropdownMenuContent>
                  {(Object.keys(ACTION_LABELS) as BudgetAction[]).map((value) => (
                    <DropdownMenuItem
                      key={value}
                      data-testid={`budget-action-${value}`}
                      onSelect={() => setAction(value)}
                    >
                      {ACTION_LABELS[value]}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            <Button
              type="button"
              data-testid="budget-save"
              loading={save.isPending}
              disabled={limit.trim() === ""}
              onClick={() => save.mutate()}
            >
              Save budget
            </Button>
            {hasBudget && (
              <Button
                type="button"
                variant="secondary"
                data-testid="budget-clear"
                loading={clear.isPending}
                onClick={() => clear.mutate()}
              >
                Remove
              </Button>
            )}
            {save.isError && <ErrorBanner error={save.error} />}
            {clear.isError && <ErrorBanner error={clear.error} />}
          </div>
        </Can>
      </CardContent>
    </Card>
  );
}
