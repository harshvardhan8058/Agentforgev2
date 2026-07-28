import type { JSX } from "react";
import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { axe } from "vitest-axe";
import { toHaveNoViolations } from "vitest-axe/dist/matchers.js";

// vitest-axe ships its type augmentation for an older Vitest `Vi` namespace;
// declare the matcher against Vitest's `Assertion` interface directly.
declare module "vitest" {
  // Must match Vitest's own `Assertion<T = any>` type-parameter signature.
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}

import { Button } from "./Button";
import { Input } from "./Input";
import { Badge } from "./Badge";
import { Card, CardContent, CardHeader, CardTitle } from "./Card";
import { Skeleton } from "./Skeleton";
import {
  Dialog,
  DialogTrigger,
  DialogContent,
} from "./Dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "./DropdownMenu";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "./Popover";

expect.extend({ toHaveNoViolations });

// jsdom can't compute layout/contrast, and axe's landmark region rule is not
// meaningful for isolated component subtrees — disable those two rules only.
const AXE_OPTIONS = {
  rules: {
    "color-contrast": { enabled: false },
    region: { enabled: false },
  },
} as const;

/**
 * Task 10.1 — component/a11y tests for the UI primitives.
 * _Requirements: 4.1_
 */
describe("ui primitives — token-driven rendering", () => {
  it("Button renders a native button with token classes and an accessible name", () => {
    render(<Button>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button.className).toContain("bg-primary");
    expect(button.className).toContain("text-primary-fg");
  });

  it("Button shows a spinner and is disabled while loading", () => {
    render(<Button loading>Save</Button>);
    const button = screen.getByRole("button", { name: /save/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(screen.getByTestId("button-spinner")).toBeInTheDocument();
  });

  it("Input carries token classes and forwards native props", () => {
    render(<Input placeholder="email" aria-label="Email" />);
    const input = screen.getByLabelText("Email");
    expect(input).toHaveAttribute("placeholder", "email");
    expect(input.className).toContain("bg-surface");
  });

  it("Badge maps a tone to token classes", () => {
    render(<Badge tone="success">Grounded</Badge>);
    const badge = screen.getByText("Grounded");
    expect(badge.className).toContain("text-success");
  });

  it("Card composes surface + border tokens", () => {
    render(
      <Card data-testid="card">
        <CardHeader>
          <CardTitle>Usage</CardTitle>
        </CardHeader>
        <CardContent>body</CardContent>
      </Card>,
    );
    const card = screen.getByTestId("card");
    expect(card.className).toContain("bg-surface");
    expect(card.className).toContain("border-border");
    expect(screen.getByText("Usage")).toBeInTheDocument();
  });

  it("Skeleton renders an aria-hidden shimmer placeholder", () => {
    render(<Skeleton className="h-4 w-24" />);
    const sk = screen.getByTestId("skeleton");
    expect(sk).toHaveAttribute("aria-hidden", "true");
    expect(sk.className).toContain("animate-pulse");
  });
});

describe("Dialog — focus trap, restore, and keyboard operability", () => {
  function DialogHarness(): JSX.Element {
    return (
      <Dialog>
        <DialogTrigger asChild>
          <Button>Open dialog</Button>
        </DialogTrigger>
        <DialogContent title="Confirm action" description="Please confirm.">
          <Button>Confirm</Button>
        </DialogContent>
      </Dialog>
    );
  }

  it("opens from the trigger, moves focus inside, and traps it", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    await user.click(trigger);

    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText("Confirm action")).toBeInTheDocument();
    // Focus has moved into the dialog (not left on the trigger).
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(document.activeElement).not.toBe(trigger);
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<DialogHarness />);
    const trigger = screen.getByRole("button", { name: "Open dialog" });
    await user.click(trigger);
    await screen.findByRole("dialog");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("has no axe violations when open", async () => {
    const user = userEvent.setup();
    const { baseElement } = render(<DialogHarness />);
    await user.click(screen.getByRole("button", { name: "Open dialog" }));
    await screen.findByRole("dialog");
    const results = await axe(baseElement, AXE_OPTIONS);
    expect(results).toHaveNoViolations();
  });
});

describe("DropdownMenu — keyboard operability and focus restore", () => {
  function MenuHarness(): JSX.Element {
    return (
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button>Actions</Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent>
          <DropdownMenuItem>New query</DropdownMenuItem>
          <DropdownMenuItem>Start run</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    );
  }

  it("opens with the keyboard and exposes menu items", async () => {
    const user = userEvent.setup();
    render(<MenuHarness />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    trigger.focus();
    await user.keyboard("{Enter}");

    const menu = await screen.findByRole("menu");
    const items = within(menu).getAllByRole("menuitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("New query");
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<MenuHarness />);
    const trigger = screen.getByRole("button", { name: "Actions" });
    await user.click(trigger);
    await screen.findByRole("menu");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("Popover — focus trap and keyboard operability", () => {
  function PopoverHarness(): JSX.Element {
    return (
      <Popover>
        <PopoverTrigger asChild>
          <Button>Open popover</Button>
        </PopoverTrigger>
        <PopoverContent>
          <Button>Inside</Button>
        </PopoverContent>
      </Popover>
    );
  }

  it("opens from the trigger and moves focus into the content", async () => {
    const user = userEvent.setup();
    render(<PopoverHarness />);
    const trigger = screen.getByRole("button", { name: "Open popover" });
    await user.click(trigger);

    const inside = await screen.findByRole("button", { name: "Inside" });
    expect(inside).toBeInTheDocument();
    expect(document.activeElement).not.toBe(trigger);
  });

  it("closes on Escape and restores focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<PopoverHarness />);
    const trigger = screen.getByRole("button", { name: "Open popover" });
    await user.click(trigger);
    await screen.findByRole("button", { name: "Inside" });

    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("button", { name: "Inside" }),
    ).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
});

describe("a11y — representative primitive usage", () => {
  it("finds no violations on a labeled form-ish composition", async () => {
    const { container } = render(
      <main>
        <Card>
          <CardHeader>
            <CardTitle>Sign in</CardTitle>
          </CardHeader>
          <CardContent>
            <form>
              <label htmlFor="email">Email</label>
              <Input id="email" name="email" type="email" />
              <label htmlFor="password">Password</label>
              <Input id="password" name="password" type="password" />
              <Badge tone="info">Beta</Badge>
              <Button type="submit">Continue</Button>
            </form>
          </CardContent>
        </Card>
      </main>,
    );
    const results = await axe(container, AXE_OPTIONS);
    expect(results).toHaveNoViolations();
  });
});
