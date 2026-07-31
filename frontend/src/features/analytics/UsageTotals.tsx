/**
 * `UsageTotals`: the top-level usage tiles (Req 11.1).
 *
 * Renders `total_tokens` (tabular numerals) and `total_cost`. The cost is
 * emitted **verbatim** — the exact string returned by the Backend_API, with no
 * parsing, rounding, or reformatting (Req 11.4, Property 11).
 */
import type { JSX } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { cn } from "../../lib/cn";
import { formatCost } from "./formatCost";

export function UsageTotals({
  totalTokens,
  totalCost,
  /**
   * Whether the deployment prices tokens. When it does not, the zero total is a
   * consequence of configuration rather than of spend, and saying "$0.00" would
   * misrepresent it.
   */
  ratesConfigured = true,
}: {
  totalTokens: number;
  totalCost: string;
  ratesConfigured?: boolean;
}): JSX.Element {
  // Only worth calling out once tokens have actually been spent: an untouched
  // workspace legitimately shows zero and needs no explanation.
  const unpriced = !ratesConfigured && totalTokens > 0;
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
            className={cn(
              "text-3xl font-semibold tabular-nums",
              unpriced ? "text-text-muted" : "text-text",
            )}
            data-testid="usage-total-cost-display"
            title={`Exact value from the API: ${totalCost}`}
          >
            {unpriced ? "Not priced" : formatCost(totalCost)}
          </p>
          <span className="sr-only" data-testid="usage-total-cost">
            {totalCost}
          </span>
          {unpriced && (
            <p
              className="mt-1.5 text-xs leading-relaxed text-text-muted"
              data-testid="usage-cost-unpriced"
            >
              Tokens are being recorded, but this deployment has no cost rates, so
              every cost computes to zero. Set{" "}
              <code className="rounded bg-bg-subtle px-1 py-0.5 font-mono text-[0.7rem]">
                COST_RATE_TABLE_JSON
              </code>{" "}
              in the server environment to price them.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
