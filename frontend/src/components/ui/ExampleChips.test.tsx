// @vitest-environment jsdom
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ExampleChips } from "./ExampleChips";

/**
 * `ExampleChips` supports two shapes because several presets are full
 * sentences. Rendering those verbatim produced a row of very long pills, so the
 * `{ label, value }` form lets the chip stay short while still inserting the
 * full text. Both halves of that contract are pinned here.
 */
describe("ExampleChips", () => {
  it("renders a bare string as both the label and the inserted value", async () => {
    const onPick = vi.fn();
    render(<ExampleChips examples={["Summarize this"]} onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: "Summarize this" }));

    expect(onPick).toHaveBeenCalledWith("Summarize this");
  });

  it("renders the short label but inserts the full value", async () => {
    const onPick = vi.fn();
    render(
      <ExampleChips
        examples={[{ label: "Incident", value: "Summarize the Q3 outage in detail." }]}
        onPick={onPick}
      />,
    );

    const chip = screen.getByRole("button", { name: "Incident" });
    await userEvent.click(chip);

    expect(onPick).toHaveBeenCalledWith("Summarize the Q3 outage in detail.");
  });

  it("exposes the full value as the chip title when it differs from the label", () => {
    render(
      <ExampleChips
        examples={[{ label: "Incident", value: "Summarize the Q3 outage." }]}
        onPick={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Incident" })).toHaveAttribute(
      "title",
      "Summarize the Q3 outage.",
    );
  });

  it("omits a redundant title when the label already is the value", () => {
    render(<ExampleChips examples={["Short"]} onPick={vi.fn()} />);

    expect(screen.getByRole("button", { name: "Short" })).not.toHaveAttribute(
      "title",
    );
  });

  it("uses type=button so a chip inside a form never submits it", async () => {
    // Every call site sits inside a <form>; a default-type button would submit.
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <ExampleChips examples={["Pick me"]} onPick={vi.fn()} />
      </form>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Pick me" }));

    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("renders the custom label and test id", () => {
    render(
      <ExampleChips
        label="Your datasets"
        examples={["ds-1"]}
        onPick={vi.fn()}
        testId="dataset-chips"
      />,
    );

    expect(screen.getByTestId("dataset-chips")).toBeInTheDocument();
    expect(screen.getByText("Your datasets:")).toBeInTheDocument();
  });

  it("is reachable by keyboard", async () => {
    const onPick = vi.fn();
    render(<ExampleChips examples={["Pick me"]} onPick={onPick} />);

    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Pick me" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");

    expect(onPick).toHaveBeenCalledWith("Pick me");
  });
});
