/**
 * `UsageDashboardView`: the analytics / usage dashboard (`/analytics`,
 * Req 11.1–11.6, 4.1).
 *
 * Calls `GET /analytics/usage` for the active Org_Context, showing
 * `total_tokens` + `total_cost` and the `by_provider` / `by_model` / `by_user`
 * breakdowns (key, tokens, cost). A start/end range control adds the `start` /
 * `end` query params. Every cost is rendered **verbatim** (Req 11.4,
 * Property 11) in the tiles/tables; the charts only position/label values.
 *
 * Premium UX: charts are **lazy-loaded** (`React.lazy` + `Suspense`, kept out
 * of the initial bundle) and **mocked in tests**; skeleton loaders match the
 * final layout; an explicit empty usage state covers a no-record range; and
 * each breakdown is wrapped in its own error boundary so one failing breakdown
 * is isolated while totals and the others still render (Req 11.6). Gated behind
 * `read`.
 */
import type { JSX } from "react";
import { Suspense, lazy, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { BarChart3 } from "lucide-react";
import { PageHeader } from "../../components/ui/PageHeader";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { can } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { EmptyState } from "../../components/EmptyState";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";
import { BREAKDOWN_GROUPS, type UsageReport } from "./types";
import { RANGE_PRESETS } from "./rangePresets";
import { UsageTotals } from "./UsageTotals";
import { UsageBreakdownTable } from "./UsageBreakdownTable";
import { BreakdownBoundary } from "./BreakdownBoundary";
import { BudgetCard } from "./BudgetCard";
import { CostRatesPanel } from "./CostRatesPanel";

// Code-split the charting layer: kept out of the initial bundle and mocked in
// tests (the module default-exports the chart component for `React.lazy`).
const UsageCharts = lazy(() => import("./UsageCharts"));

function isEmptyReport(report: UsageReport): boolean {
  return (
    report.total_tokens === 0 &&
    report.by_provider.length === 0 &&
    report.by_model.length === 0 &&
    report.by_user.length === 0
  );
}

export function UsageDashboardView(): JSX.Element {
  const { orgId, role } = useSession();
  const permitted = role !== null && can(role, "read");

  // Draft range inputs vs. the applied range that drives the query key.
  const [draftStart, setDraftStart] = useState("");
  const [draftEnd, setDraftEnd] = useState("");
  const [start, setStart] = useState<string>("");
  const [end, setEnd] = useState<string>("");

  const usage = useQuery<UsageReport, ClientError>({
    enabled: permitted,
    queryKey: orgScopedKey(orgId, "usage", start, end),
    queryFn: async () => {
      const data = await runRequest(() =>
        apiClient.GET("/analytics/usage", {
          params: {
            query: {
              start: start.length > 0 ? start : undefined,
              end: end.length > 0 ? end : undefined,
            },
          },
        }),
      );
      return {
        org_id: data.org_id,
        start: data.start,
        end: data.end,
        total_tokens: data.total_tokens,
        total_cost: data.total_cost,
        by_provider: data.by_provider ?? [],
        by_model: data.by_model ?? [],
        by_user: data.by_user ?? [],
        // Defaulted true so an older API that omits the field is not accused of
        // being unpriced; the flag only ever downgrades a confident figure.
        cost_rates_configured: data.cost_rates_configured ?? true,
      };
    },
  });

  const report = usage.data;

  return (
    <div className="flex flex-col gap-6" data-testid="analytics-view">
      <PageHeader
        eyebrow="Platform"
        icon={BarChart3}
        title="Analytics"
        description="Token usage and cost for your organization."
      />

      {!permitted && (
        <EmptyState
          title="Analytics unavailable"
          message="Your role does not permit viewing usage analytics in this organization."
          icon={<BarChart3 className="h-8 w-8" />}
        />
      )}

      {permitted && (
        <>
          <Card data-testid="range-picker-card">
            <CardHeader>
              <CardTitle className="text-base">Time range</CardTitle>
            </CardHeader>
            <CardContent>
              <form
                className="flex flex-wrap items-end gap-3"
                data-testid="range-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  setStart(draftStart);
                  setEnd(draftEnd);
                }}
              >
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="usage-start" className="text-sm font-medium text-text">
                    Start
                  </label>
                  <Input
                    id="usage-start"
                    data-testid="usage-start"
                    type="datetime-local"
                    value={draftStart}
                    onChange={(e) => setDraftStart(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="usage-end" className="text-sm font-medium text-text">
                    End
                  </label>
                  <Input
                    id="usage-end"
                    data-testid="usage-end"
                    type="datetime-local"
                    value={draftEnd}
                    onChange={(e) => setDraftEnd(e.target.value)}
                  />
                </div>
                <Button type="submit" data-testid="range-apply">
                  Apply range
                </Button>
              </form>

              {/* Quick ranges. These apply immediately rather than only filling
                  the inputs: a preset is an expressed intent ("last 7 days"),
                  so making the Operator then press Apply would be a pointless
                  second step. */}
              <div
                className="mt-3 flex flex-wrap items-center gap-1.5"
                data-testid="range-presets"
              >
                <span className="text-xs font-medium text-text-subtle">Quick:</span>
                {RANGE_PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    type="button"
                    data-testid={`range-preset-${preset.label
                      .toLowerCase()
                      .replace(/\s+/g, "-")}`}
                    onClick={() => {
                      const [nextStart, nextEnd] = preset.resolve(new Date());
                      setDraftStart(nextStart);
                      setDraftEnd(nextEnd);
                      setStart(nextStart);
                      setEnd(nextEnd);
                    }}
                    className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-text-muted transition-colors hover:border-primary/60 hover:bg-primary-subtle hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>

          {usage.isError && (
            <div data-testid="analytics-error">
              <ErrorBanner error={usage.error} onRetry={() => void usage.refetch()} />
            </div>
          )}

          {usage.isLoading && (
            <div className="flex flex-col gap-3" data-testid="analytics-skeleton">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <Skeleton className="h-24 w-full" />
                <Skeleton className="h-24 w-full" />
              </div>
              <Skeleton className="h-48 w-full" />
            </div>
          )}

          {report && !usage.isLoading && isEmptyReport(report) && (
            <div data-testid="analytics-empty">
              <EmptyState
                title="No usage recorded yet"
                message="Usage and cost accrue here as you run grounded queries and agent runs. Try a query, then widen the time range to see the breakdown by provider, model, and user."
                icon={<BarChart3 className="h-8 w-8" />}
              />
            </div>
          )}

          {report && !usage.isLoading && !isEmptyReport(report) && (
            <div className="flex flex-col gap-6" data-testid="analytics-content">
              <UsageTotals
                totalTokens={report.total_tokens}
                totalCost={report.total_cost}
                ratesConfigured={report.cost_rates_configured}
              />

              <Suspense
                fallback={<Skeleton className="h-48 w-full" data-testid="charts-skeleton" />}
              >
                <UsageCharts
                  sections={BREAKDOWN_GROUPS.map((g) => ({
                    id: g.id,
                    label: g.label,
                    entries: report[g.id],
                  }))}
                />
              </Suspense>

              <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                {BREAKDOWN_GROUPS.map((g) => (
                  <BreakdownBoundary key={g.id} group={g.id} label={g.label}>
                    <UsageBreakdownTable
                      group={g.id}
                      label={g.label}
                      entries={report[g.id]}
                    />
                  </BreakdownBoundary>
                ))}
              </div>
            </div>
          )}

          {/* The budget is governance, not usage: it renders whether or not this range
              recorded anything, because setting a ceiling is most useful before the spend
              happens. */}
          <BudgetCard />

          {/* Pricing is deployment configuration, not usage, so it renders
              regardless of whether this range recorded anything — an operator
              setting the platform up needs it most when there is no usage yet. */}
          {!usage.isLoading && <CostRatesPanel />}
        </>
      )}
    </div>
  );
}
