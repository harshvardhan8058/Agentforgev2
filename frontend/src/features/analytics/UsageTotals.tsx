/**
 * `UsageTotals`: the top-level usage tiles (Req 11.1).
 *
 * Renders `total_tokens` (tabular numerals) and `total_cost`. The cost is
 * emitted **verbatim** — the exact string returned by the Backend_API, with no
 * parsing, rounding, or reformatting (Req 11.4, Property 11).
 */
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { formatCost } from "./formatCost";

export function UsageTotals({
  totalTokens,
  totalCost,
}: {
  totalTokens: number;
  totalCost: string;
}): JSX.Element {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2" data-testid="usage-totals">
      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-text-muted">Total tokens</CardTitle>
        </CardHeader>
        <CardContent>
          <p
            className="text-3xl font-semibold tabular-nums text-text"
            data-testid="usage-total-tokens"
          >
            {totalTokens}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-text-muted">Total cost</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Friendly, human-readable primary display. */}
          <p
            className="text-3xl font-semibold tabular-nums text-text"
            data-testid="usage-total-cost-display"
          >
            {formatCost(totalCost)}
          </p>
          {/* The exact backend string, preserved verbatim (Req 11.4, Property 11). */}
          <p className="mt-1 text-xs text-text-subtle">
            Exact:{" "}
            <span className="font-mono tabular-nums" data-testid="usage-total-cost">
              {totalCost}
            </span>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
