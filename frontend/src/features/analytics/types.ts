/**
 * Client-side analytics types (mirroring the generated
 * `UsageReportResponse` / `UsageBreakdownEntry` shapes in `schema.d.ts`).
 *
 * These are the exact shapes `GET /analytics/usage` resolves to; `total_cost`
 * is a **string** that the Web_Client renders **verbatim** — never parsed,
 * rounded, or reformatted (Req 11.4, Property 11).
 */

/** One grouped row of a usage breakdown (by provider / model / user). */
export interface UsageBreakdownEntry {
  key: string;
  total_tokens: number;
  /** EXACT cost string from the backend; rendered verbatim (Req 11.4). */
  total_cost: string;
}

/** The org-scoped usage/cost aggregation over `[start, end]`. */
export interface UsageReport {
  org_id: string;
  start: string;
  end: string;
  total_tokens: number;
  /** EXACT cost string from the backend; rendered verbatim (Req 11.4). */
  total_cost: string;
  by_provider: UsageBreakdownEntry[];
  by_model: UsageBreakdownEntry[];
  by_user: UsageBreakdownEntry[];
  /**
   * Whether the deployment prices tokens at all.
   *
   * Costs default to zero, so a zero total means either "nothing spent" or
   * "nothing priced" — indistinguishable from the figures alone. Presenting an
   * unpriced deployment's total as a confident `$0.00` beside a five-figure
   * token count reads as a broken cost feature, so the two are shown
   * differently.
   */
  cost_rates_configured: boolean;
}

/** The three breakdown groupings, in display order. */
export const BREAKDOWN_GROUPS = [
  { id: "by_provider", label: "By provider" },
  { id: "by_model", label: "By model" },
  { id: "by_user", label: "By user" },
] as const;

export type BreakdownGroupId = (typeof BREAKDOWN_GROUPS)[number]["id"];
