/**
 * `UsageTotals`: the top-level usage tiles (Req 11.1).
 *
 * Renders `total_tokens` (tabular numerals) and `total_cost`. The cost is
 * emitted **verbatim** — the exact string returned by the Backend_API, with no
 * parsing, rounding, or reformatting (Req 11.4, Property 11).
 */
import type { JSX } from "react";
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
          {/*
            The backend returns an exact Decimal string, which serializes forms
            like `0E-8` and `10.0000`. Printing that next to the total as
            "Exact: 0E-8" read as a defect rather than as precision, so the
            formatted value is the visible one and the exact string is carried
            verbatim in the adjacent element (Req 11.4, Property 11) — the same
            arrangement the per-breakdown tables already use. It also stays on
            the title, so it can be read without a screen reader.
          */}
          <p
            className="text-3xl font-semibold tabular-nums text-text"
            data-testid="usage-total-cost-display"
            title={`Exact value from the API: ${totalCost}`}
          >
            {formatCost(totalCost)}
          </p>
          <span className="sr-only" data-testid="usage-total-cost">
            {totalCost}
          </span>
        </CardContent>
      </Card>
    </div>
  );
}
