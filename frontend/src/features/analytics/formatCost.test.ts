import { describe, it, expect } from "vitest";

import { formatCost } from "./formatCost";

/**
 * `formatCost` produces a friendly currency companion for the verbatim cost
 * string. It must normalize the ugly `Decimal` serializations (e.g. `0E-8`)
 * while never fabricating a value for non-numeric input.
 */
describe("formatCost", () => {
  it("renders a zero decimal (incl. scientific 0E-8) as $0.00", () => {
    expect(formatCost("0E-8")).toBe("$0.00");
    expect(formatCost("0")).toBe("$0.00");
    expect(formatCost("0.00")).toBe("$0.00");
  });

  it("pads whole/one-decimal values to at least two decimals", () => {
    expect(formatCost("10.0000")).toBe("$10.00");
    expect(formatCost("2.5")).toBe("$2.50");
  });

  it("preserves sub-cent precision up to six fraction digits", () => {
    expect(formatCost("12.3456")).toBe("$12.3456");
    expect(formatCost("0.000123")).toBe("$0.000123");
  });

  it("adds thousands separators for large amounts", () => {
    expect(formatCost("1234.5")).toBe("$1,234.50");
  });

  it("returns non-numeric input unchanged (never fabricates a value)", () => {
    expect(formatCost("n/a")).toBe("n/a");
    expect(formatCost("abc")).toBe("abc");
  });
});
