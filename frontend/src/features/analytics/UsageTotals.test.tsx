// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { UsageTotals } from "./UsageTotals";

/**
 * The cost tile has to distinguish "nothing spent" from "nothing priced".
 *
 * Costs default to zero, so both render as a zero total. The console showed the
 * unpriced case as a confident "$0.00" beside 54,915 tokens, which reads as a
 * broken cost feature rather than an unconfigured one. `cost_rates_configured`
 * comes from the API precisely so the client does not have to guess.
 *
 * The verbatim cost element is asserted here too, because it is load-bearing:
 * Property 11 requires the exact backend string to be present, and it must
 * survive whichever presentation branch is taken.
 */
describe("UsageTotals", () => {
  it("shows the formatted cost when rates are configured", () => {
    render(
      <UsageTotals totalTokens={1000} totalCost="12.3456" ratesConfigured />,
    );

    expect(screen.getByTestId("usage-total-cost-display").textContent).toBe(
      "$12.3456",
    );
    expect(screen.queryByTestId("usage-cost-unpriced")).not.toBeInTheDocument();
  });

  it("does not claim $0.00 when tokens were spent but nothing is priced", () => {
    render(
      <UsageTotals
        totalTokens={54915}
        totalCost="0E-8"
        ratesConfigured={false}
      />,
    );

    expect(screen.getByTestId("usage-total-cost-display").textContent).toBe(
      "Not priced",
    );
    expect(screen.getByTestId("usage-cost-unpriced")).toBeInTheDocument();
  });

  it("names the setting that fixes it", () => {
    // A dead end is worse than a wrong number; the operator needs the next step.
    render(
      <UsageTotals totalTokens={100} totalCost="0" ratesConfigured={false} />,
    );

    expect(screen.getByTestId("usage-cost-unpriced").textContent).toContain(
      "COST_RATE_TABLE_JSON",
    );
  });

  it("stays quiet on an untouched workspace", () => {
    // Zero tokens and zero cost is simply true, and needs no explanation.
    render(
      <UsageTotals totalTokens={0} totalCost="0" ratesConfigured={false} />,
    );

    expect(screen.queryByTestId("usage-cost-unpriced")).not.toBeInTheDocument();
    expect(screen.getByTestId("usage-total-cost-display").textContent).toBe("$0.00");
  });

  it("keeps the verbatim cost string in both branches (Property 11)", () => {
    const { unmount } = render(
      <UsageTotals totalTokens={54915} totalCost="0E-8" ratesConfigured={false} />,
    );
    expect(screen.getByTestId("usage-total-cost").textContent).toBe("0E-8");
    unmount();

    render(<UsageTotals totalTokens={10} totalCost="1.500000" ratesConfigured />);
    expect(screen.getByTestId("usage-total-cost").textContent).toBe("1.500000");
  });

  it("defaults to treating rates as configured", () => {
    // An older API that omits the flag must not be accused of being unpriced.
    render(<UsageTotals totalTokens={100} totalCost="0" />);

    expect(screen.queryByTestId("usage-cost-unpriced")).not.toBeInTheDocument();
  });

  it("renders the token total", () => {
    render(<UsageTotals totalTokens={54915} totalCost="0" ratesConfigured />);

    expect(screen.getByTestId("usage-total-tokens").textContent).toBe("54915");
  });
});
