// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import UsageCharts from "./UsageCharts";
import type { UsageBreakdownEntry } from "./types";

/**
 * `UsageCharts` renders a chart only where there is a distribution to see.
 *
 * A fresh workspace has one provider serving one model for one user, so every
 * breakdown held exactly one entry and the dashboard drew three identical
 * single-bar charts — each restating a number already present in the totals tile
 * and the table underneath. A chart that cannot compare anything is noise, so
 * the component now suppresses it.
 */
function entry(key: string, tokens: number): UsageBreakdownEntry {
  return { key, total_tokens: tokens, total_cost: "0" };
}

describe("UsageCharts", () => {
  it("renders nothing when every breakdown has a single entry", () => {
    const { container } = render(
      <UsageCharts
        sections={[
          { id: "by_provider", label: "By provider", entries: [entry("groq", 10)] },
          { id: "by_model", label: "By model", entries: [entry("llama", 10)] },
          { id: "by_user", label: "By user", entries: [entry("u1", 10)] },
        ]}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when every breakdown is empty", () => {
    const { container } = render(
      <UsageCharts
        sections={[{ id: "by_provider", label: "By provider", entries: [] }]}
      />,
    );

    expect(container.firstChild).toBeNull();
  });

  it("renders only the breakdowns that have something to compare", () => {
    render(
      <UsageCharts
        sections={[
          {
            id: "by_provider",
            label: "By provider",
            entries: [entry("groq", 10), entry("fallback", 4)],
          },
          { id: "by_model", label: "By model", entries: [entry("llama", 14)] },
          { id: "by_user", label: "By user", entries: [] },
        ]}
      />,
    );

    expect(screen.getByTestId("usage-chart-by_provider")).toBeInTheDocument();
    expect(screen.queryByTestId("usage-chart-by_model")).not.toBeInTheDocument();
    expect(screen.queryByTestId("usage-chart-by_user")).not.toBeInTheDocument();
  });

  it("labels each rendered chart", () => {
    render(
      <UsageCharts
        sections={[
          {
            id: "by_user",
            label: "By user",
            entries: [entry("ada", 10), entry("grace", 7)],
          },
        ]}
      />,
    );

    expect(screen.getByText("By user")).toBeInTheDocument();
  });
});
