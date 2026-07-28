/**
 * `formatCost`: a friendly, human-readable rendering of a backend cost string
 * for **display alongside** the verbatim value.
 *
 * The Backend_API returns costs as exact decimal strings (a `Decimal`), which
 * can surface as `0E-8` or `10.0000`. Those exact strings are still rendered
 * verbatim in a dedicated element (Req 11.4, Property 11); this helper produces
 * a readable companion (e.g. `$0.00`, `$10.00`, `$1,234.50`) for the primary
 * visual. It is pure and total: any non-numeric input is returned unchanged so
 * an unexpected value is never misrepresented.
 */
export function formatCost(raw: string): string {
  const n = Number(raw);
  // Non-numeric (or non-finite) input: never fabricate a currency value.
  if (!Number.isFinite(n)) return raw;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    // Keep sub-cent precision visible (token costs are often tiny fractions).
    maximumFractionDigits: 6,
  });
}
