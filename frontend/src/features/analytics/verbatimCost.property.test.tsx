// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import fc from "fast-check";

import { UsageTotals } from "./UsageTotals";
import { UsageBreakdownTable } from "./UsageBreakdownTable";
import type { UsageBreakdownEntry } from "./types";

/**
 * Task 22.1 — Property 11: Usage cost strings are rendered verbatim.
 * _Validates: Requirements 11.4, 11.3_
 *
 * For any UsageReport with arbitrary cost strings, every displayed cost (the
 * top-level total and each breakdown entry) equals the EXACT backend string,
 * with no parsing/rounding/reformatting. The assertion reads the rendered DOM
 * `textContent` directly (not RTL's whitespace-normalizing matcher) so a
 * verbatim mismatch — including whitespace — would fail.
 */

const costArb = fc.string();

const entryArb: fc.Arbitrary<UsageBreakdownEntry> = fc.record({
  key: fc.string(),
  total_tokens: fc.nat(),
  total_cost: costArb,
});

describe("Usage cost rendering (Property 11)", () => {
  // Feature: agentforge-frontend, Property 11: Usage cost strings are rendered verbatim
  it("Property 11: renders the top-level total_cost verbatim", () => {
    fc.assert(
      fc.property(costArb, fc.nat(), (totalCost, totalTokens) => {
        const { getByTestId, unmount } = render(
          <UsageTotals totalTokens={totalTokens} totalCost={totalCost} />,
        );
        expect(getByTestId("usage-total-cost").textContent).toBe(totalCost);
        unmount();
      }),
      { numRuns: 120 },
    );
  });

  // Feature: agentforge-frontend, Property 11: Usage cost strings are rendered verbatim
  it("Property 11: renders every breakdown entry cost verbatim", () => {
    fc.assert(
      fc.property(fc.array(entryArb, { maxLength: 8 }), (entries) => {
        const { getByTestId, unmount } = render(
          <UsageBreakdownTable group="by_provider" label="By provider" entries={entries} />,
        );
        entries.forEach((entry, i) => {
          expect(getByTestId(`breakdown-by_provider-cost-${i}`).textContent).toBe(
            entry.total_cost,
          );
        });
        unmount();
      }),
      { numRuns: 120 },
    );
  });
});
