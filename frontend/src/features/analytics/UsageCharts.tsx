/**
 * `UsageCharts`: the interactive usage/cost visualization (Premium UX §3).
 *
 * Charts **position and label** breakdown values but never become the
 * authoritative cost string shown to the Operator — the verbatim `total_cost`
 * strings live in the tiles/tables (Req 11.4, Property 11). This module is
 * **code-split** (loaded via `React.lazy` + `Suspense` on the analytics route,
 * kept out of the initial bundle) and **mocked in tests** with a lightweight
 * stub so the suite stays keyless, fast, and deterministic.
 *
 * Default-exported so it can be consumed by `React.lazy`.
 */
import type { JSX } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { UsageBreakdownEntry } from "./types";

interface ChartSection {
  id: string;
  label: string;
  entries: UsageBreakdownEntry[];
}

/** Compact axis number formatting: 1234 -> "1.2k", 1_500_000 -> "1.5M". */
function compactNumber(value: number): string {
  if (!Number.isFinite(value)) return "";
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (abs >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(value);
}

/** Full, thousands-separated tokens for the tooltip. */
function formatTokens(value: number): string {
  return `${value.toLocaleString("en-US")} tokens`;
}

/**
 * Token-count bar charts for the breakdowns (tokens are numeric and safe to
 * plot; costs remain verbatim strings in the tables).
 */
export default function UsageCharts({
  sections,
}: {
  sections: ChartSection[];
}): JSX.Element | null {
  /*
   * A breakdown with a single entry has nothing to compare, so its chart is one
   * lone bar restating a number already shown in the totals tile and the table
   * below. With one provider serving one model for one user — the normal case
   * for a fresh workspace — that rendered three identical charts side by side.
   * Charts are therefore shown only where there is a distribution to see, and
   * appear on their own as usage diversifies.
   */
  const comparable = sections.filter((s) => s.entries.length > 1);
  if (comparable.length === 0) return null;

  return (
    <div
      className={
        comparable.length === 1
          ? "grid grid-cols-1 gap-4"
          : "grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3"
      }
      data-testid="usage-charts"
    >
      {comparable.map((section) => (
        <div
          key={section.id}
          className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3"
          data-testid={`usage-chart-${section.id}`}
        >
          <span className="text-sm font-semibold text-text">{section.label}</span>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={section.entries.map((e) => ({ key: e.key, tokens: e.total_tokens }))}
                margin={{ top: 8, right: 8, bottom: 4, left: 4 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="var(--color-border)"
                  vertical={false}
                />
                <XAxis
                  dataKey="key"
                  tick={{ fontSize: 11, fill: "var(--color-text-muted)" }}
                  tickLine={false}
                  axisLine={{ stroke: "var(--color-border)" }}
                  interval={0}
                  tickMargin={6}
                />
                <YAxis
                  tick={{ fontSize: 11, fill: "var(--color-text-muted)" }}
                  tickLine={false}
                  axisLine={false}
                  width={44}
                  tickFormatter={compactNumber}
                  allowDecimals={false}
                />
                <Tooltip
                  cursor={{ fill: "var(--color-surface-hover)" }}
                  formatter={(value) => [formatTokens(Number(value)), "Tokens"]}
                  contentStyle={{
                    background: "var(--color-surface-raised)",
                    border: "1px solid var(--color-border-strong)",
                    borderRadius: "0.5rem",
                    fontSize: "0.75rem",
                    color: "var(--color-text)",
                  }}
                  labelStyle={{ color: "var(--color-text-muted)" }}
                />
                <Bar
                  dataKey="tokens"
                  fill="var(--color-primary)"
                  radius={[4, 4, 0, 0]}
                  maxBarSize={64}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      ))}
    </div>
  );
}
