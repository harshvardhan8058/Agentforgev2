// @vitest-environment jsdom
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSelectTrigger,
} from "./DropdownMenu";

/**
 * `DropdownMenuSelectTrigger` exists because the role and team pickers were
 * bordered boxes the same height and colour as a text `Input`, with no indicator
 * that they open a list — the current value simply looked like text somebody had
 * typed. The trailing chevron is the affordance, so it is asserted here rather
 * than left to each caller to remember.
 */
function renderTrigger(props: {
  value?: string;
  placeholder?: string;
} = {}): void {
  render(
    <DropdownMenu>
      <DropdownMenuSelectTrigger
        data-testid="trigger"
        aria-label="Role"
        {...props}
      />
      <DropdownMenuContent>
        <DropdownMenuItem>owner</DropdownMenuItem>
        <DropdownMenuItem>viewer</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>,
  );
}

describe("DropdownMenuSelectTrigger", () => {
  it("renders the current value", () => {
    renderTrigger({ value: "owner" });

    expect(screen.getByTestId("trigger").textContent).toContain("owner");
  });

  it("always renders a chevron, the cue that it opens a list", () => {
    renderTrigger({ value: "owner" });

    // Decorative: the button role plus aria-expanded already convey behaviour.
    const icon = screen.getByTestId("trigger").querySelector("svg");
    expect(icon).not.toBeNull();
    expect(icon).toHaveAttribute("aria-hidden", "true");
  });

  it("shows the placeholder when nothing is selected", () => {
    renderTrigger({ placeholder: "Select a team" });

    expect(screen.getByTestId("trigger").textContent).toContain("Select a team");
  });

  it("treats an empty string as no selection", () => {
    renderTrigger({ value: "", placeholder: "Select a team" });

    expect(screen.getByTestId("trigger").textContent).toContain("Select a team");
  });

  it("is a button that reports its expanded state", async () => {
    renderTrigger({ value: "owner" });
    const trigger = screen.getByTestId("trigger");

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
  });

  it("opens the menu on click", async () => {
    renderTrigger({ value: "owner" });

    await userEvent.click(screen.getByTestId("trigger"));

    expect(await screen.findByText("viewer")).toBeInTheDocument();
  });

  it("keeps a caller-supplied class alongside its own", () => {
    renderTrigger({ value: "owner" });
    render(
      <DropdownMenu>
        <DropdownMenuSelectTrigger
          data-testid="narrow"
          className="w-40"
          value="owner"
        />
      </DropdownMenu>,
    );

    expect(screen.getByTestId("narrow").className).toContain("w-40");
    expect(screen.getByTestId("narrow").className).toContain("rounded-md");
  });
});
