/**
 * `UsageTotals`: the top-level usage tiles (Req 11.1).
 *
 * Renders `total_tokens` (tabular numerals) and `total_cost`. The cost is
 * emitted **verbatim** — the exact string returned by the Backend_API, with no
 * parsing, rounding, or reformatting (Req 11.4, Property 11).
 */
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";

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
          {/* Verbatim: exactly the backend string (Req 11.4, Property 11). */}
          <p
            className="text-3xl font-semibold tabular-nums text-text"
            data-testid="usage-total-cost"
          >
            {totalCost}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
