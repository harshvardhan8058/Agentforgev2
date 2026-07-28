/**
 * `UsageBreakdownTable`: one usage breakdown grouping rendered as a table
 * (Req 11.3).
 *
 * Each row shows the entry's `key`, `total_tokens`, and `total_cost`. The cost
 * is rendered **verbatim** — the exact backend string, never reformatted
 * (Req 11.4, Property 11). This component intentionally does no defensive
 * coercion of its rows: a malformed entry surfaces as a render error that the
 * enclosing per-breakdown error boundary isolates (Req 11.6).
 */
import type { UsageBreakdownEntry } from "./types";
import { formatCost } from "./formatCost";

export function UsageBreakdownTable({
  group,
  label,
  entries,
}: {
  group: string;
  label: string;
  entries: UsageBreakdownEntry[];
}): JSX.Element {
  return (
    <div className="flex flex-col gap-2" data-testid={`breakdown-${group}`}>
      <h3 className="text-sm font-semibold text-text">{label}</h3>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="text-xs uppercase tracking-wide text-text-muted">
            <th className="py-1 font-medium">Key</th>
            <th className="py-1 text-right font-medium">Tokens</th>
            <th className="py-1 text-right font-medium">Cost</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry, i) => (
            <tr
              key={`${entry.key}-${i}`}
              className="border-t border-border"
              data-testid={`breakdown-${group}-row-${i}`}
            >
              <td className="py-1.5" data-testid={`breakdown-${group}-key-${i}`}>
                {entry.key}
              </td>
              <td
                className="py-1.5 text-right tabular-nums"
                data-testid={`breakdown-${group}-tokens-${i}`}
              >
                {entry.total_tokens}
              </td>
              {/* Friendly display; the exact backend string is preserved
                  verbatim in the adjacent element (Req 11.4, Property 11). */}
              <td className="py-1.5 text-right font-mono tabular-nums">
                <span className="text-text">{formatCost(entry.total_cost)}</span>
                <span className="sr-only" data-testid={`breakdown-${group}-cost-${i}`}>
                  {entry.total_cost}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
