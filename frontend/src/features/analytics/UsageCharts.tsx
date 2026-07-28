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

/**
 * Token-count bar charts for the breakdowns (tokens are numeric and safe to
 * plot; costs remain verbatim strings in the tables).
 */
export default function UsageCharts({
  sections,
}: {
  sections: ChartSection[];
}): JSX.Element {
  const populated = sections.filter((s) => s.entries.length > 0);

  return (
    <div
      className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3"
      data-testid="usage-charts"
    >
      {populated.map((section) => (
        <div
          key={section.id}
          className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3"
          data-testid={`usage-chart-${section.id}`}
        >
          <span className="text-sm font-semibold text-text">{section.label}</span>
          <div className="h-48 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={section.entries.map((e) => ({ key: e.key, tokens: e.total_tokens }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--af-border)" />
                <XAxis dataKey="key" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="tokens" fill="var(--af-primary)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      ))}
    </div>
  );
}
