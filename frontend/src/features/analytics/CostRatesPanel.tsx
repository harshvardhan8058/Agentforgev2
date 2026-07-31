/**
 * `CostRatesPanel`: the pricing behind every cost figure on the dashboard.
 *
 * Calls `GET /analytics/cost-rates` and renders the effective per-1K-token rates
 * — the selected preset overlaid with any explicit overrides — or, when the
 * deployment prices nothing, what to set to change that.
 *
 * This exists because a cost total is not self-explanatory: `$0.00` can mean
 * "nothing spent" or "nothing priced", and a non-zero total is unauditable
 * without the rate that produced it. `UsageTotals` already distinguishes the
 * first pair; this answers the second.
 *
 * Rates are rendered **verbatim** for the same reason costs are: they are exact
 * decimal strings (`0.00005`) that a float round-trip would corrupt.
 *
 * The panel is self-contained (its own query, its own error surface) so a
 * pricing-endpoint failure never blocks the usage report beside it.
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { Coins } from "lucide-react";

import { apiClient } from "../../api/client";
import { runRequest } from "../../api/request";
import type { ClientError } from "../../api/errors";
import { orgScopedKey } from "../../api/queryKeys";
import { useSession } from "../../auth/useSession";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Badge } from "../../components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "../../components/ui/Card";
import { Skeleton } from "../../components/ui/Skeleton";

/** One effective `(provider, model)` price, mirroring the generated `CostRateEntry`. */
interface CostRateEntry {
  provider: string;
  model: string;
  prompt_per_1k: string;
  completion_per_1k: string;
  source: "preset" | "override";
}

/** Mirrors the generated `CostRatesResponse`. */
interface CostRates {
  preset?: string | null;
  available_presets?: string[];
  default_prompt_per_1k: string;
  default_completion_per_1k: string;
  configured?: boolean;
  rates?: CostRateEntry[];
}

function isPriced(value: string): boolean {
  // An exact Decimal string; `Number` is used only for the zero test, never for
  // display, so no rounding reaches the DOM.
  return Number(value) !== 0;
}

export function CostRatesPanel(): JSX.Element {
  const { orgId } = useSession();

  const rates = useQuery<CostRates, ClientError>({
    queryKey: orgScopedKey(orgId, "cost-rates"),
    queryFn: () =>
      runRequest<CostRates>(() => apiClient.GET("/analytics/cost-rates", {})),
  });

  const data = rates.data;
  const entries = data?.rates ?? [];
  const presets = data?.available_presets ?? [];
  const defaultsPriced =
    data !== undefined &&
    (isPriced(data.default_prompt_per_1k) ||
      isPriced(data.default_completion_per_1k));

  return (
    <Card data-testid="cost-rates-panel">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <Coins className="h-4 w-4 text-text-muted" aria-hidden="true" />
          Cost rates
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {rates.isError && (
          <ErrorBanner error={rates.error} onRetry={() => void rates.refetch()} />
        )}

        {rates.isLoading && <Skeleton className="h-24 w-full" data-testid="cost-rates-skeleton" />}

        {data && (
          <>
            <p className="text-sm text-text-muted">
              {data.configured
                ? "Prices applied to recorded tokens, per 1,000 tokens."
                : "This deployment prices nothing, so every recorded cost is zero."}
              {data.preset ? (
                <>
                  {" "}
                  Preset{" "}
                  <code
                    className="rounded bg-bg-subtle px-1 py-0.5 font-mono text-[0.7rem]"
                    data-testid="cost-rates-preset"
                  >
                    {data.preset}
                  </code>
                  .
                </>
              ) : null}
            </p>

            {entries.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-sm" data-testid="cost-rates-table">
                  <caption className="sr-only">
                    Effective per-1,000-token rates by provider and model
                  </caption>
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-subtle">
                      <th scope="col" className="py-2 pr-3 font-medium">
                        Provider
                      </th>
                      <th scope="col" className="py-2 pr-3 font-medium">
                        Model
                      </th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">
                        Prompt / 1K
                      </th>
                      <th scope="col" className="py-2 pr-3 text-right font-medium">
                        Completion / 1K
                      </th>
                      <th scope="col" className="py-2 font-medium">
                        Source
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {entries.map((entry) => (
                      <tr
                        key={`${entry.provider}:${entry.model}`}
                        className="border-b border-border/60 last:border-0"
                        data-testid={`cost-rate-${entry.provider}-${entry.model}`}
                      >
                        <td className="py-2 pr-3 text-text-muted">{entry.provider}</td>
                        <td className="py-2 pr-3 font-mono text-xs text-text">
                          {entry.model}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-text">
                          {entry.prompt_per_1k}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-text">
                          {entry.completion_per_1k}
                        </td>
                        <td className="py-2">
                          <Badge tone={entry.source === "override" ? "info" : "neutral"}>
                            {entry.source}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <p className="text-xs leading-relaxed text-text-muted">
              {defaultsPriced ? (
                <>
                  Any unlisted provider/model is charged at the default rate{" "}
                  <span className="tabular-nums">{data.default_prompt_per_1k}</span> /{" "}
                  <span className="tabular-nums">{data.default_completion_per_1k}</span>{" "}
                  per 1,000 prompt / completion tokens.
                </>
              ) : (
                <>Any unlisted provider/model is charged at zero.</>
              )}
              {!data.configured && presets.length > 0 && (
                <>
                  {" "}
                  Set{" "}
                  <code className="rounded bg-bg-subtle px-1 py-0.5 font-mono text-[0.7rem]">
                    COST_RATE_PRESET
                  </code>{" "}
                  in the server environment to one of{" "}
                  <span data-testid="cost-rates-available">{presets.join(", ")}</span>, or
                  supply{" "}
                  <code className="rounded bg-bg-subtle px-1 py-0.5 font-mono text-[0.7rem]">
                    COST_RATE_TABLE_JSON
                  </code>{" "}
                  to price models individually.
                </>
              )}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
