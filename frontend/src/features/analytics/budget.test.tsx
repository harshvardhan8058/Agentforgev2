// @vitest-environment jsdom
import { describe, it, expect, beforeAll, beforeEach, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { axe } from "vitest-axe";
import { toHaveNoViolations } from "vitest-axe/dist/matchers.js";

// vitest-axe ships its type augmentation for an older Vitest `Vi` namespace.
declare module "vitest" {
  // Must match Vitest's own `Assertion<T = any>` type-parameter signature.
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}

import { BudgetCard } from "./BudgetCard";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

expect.extend({ toHaveNoViolations });

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const AXE_OPTIONS = { rules: { "color-contrast": { enabled: false } } };

function renderCard(role: Role = "owner"): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          <BudgetCard />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function status(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    period_start: "2026-08-01T00:00:00Z",
    period_end: "2026-09-01T00:00:00Z",
    spent: "0",
    limit_amount: null,
    remaining: null,
    percent_used: null,
    action: null,
    exceeded: false,
    blocked: false,
    ...overrides,
  };
}

let puts: Array<Record<string, unknown>> = [];
let deletes = 0;

beforeEach(() => {
  puts = [];
  deletes = 0;
  server.use(
    http.get(`${BASE}/budget`, () => HttpResponse.json(status())),
    http.put(`${BASE}/budget`, async ({ request }) => {
      const body = (await request.json()) as Record<string, unknown>;
      puts.push(body);
      return HttpResponse.json(
        status({
          limit_amount: String(body.limit_amount),
          action: body.action,
          remaining: String(body.limit_amount),
          percent_used: "0.00",
        }),
      );
    }),
    http.delete(`${BASE}/budget`, () => {
      deletes += 1;
      return new HttpResponse(null, { status: 204 });
    }),
  );
});

/**
 * Spend budgets: the control half of cost analytics. The platform could measure spend and
 * not limit it; this card sets the ceiling and reports where the org stands.
 */
describe("BudgetCard (MSW)", () => {
  it("says spend is unlimited when no budget is set", async () => {
    renderCard("owner");

    await waitFor(() => expect(screen.getByTestId("budget-unlimited")).toBeInTheDocument());
    expect(screen.getByTestId("budget-limit")).toHaveTextContent("No limit");
    expect(screen.getByTestId("budget-remaining")).toHaveTextContent("—");
    // No budget is not the same as a budget of zero, so no progress bar is claimed.
    expect(screen.queryByTestId("budget-progress")).toBeNull();
  });

  it("renders spend, limit and remaining verbatim", async () => {
    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(
          status({
            spent: "0.00013",
            limit_amount: "1.00",
            remaining: "0.99987",
            percent_used: "0.01",
            action: "warn",
          }),
        ),
      ),
    );

    renderCard("owner");

    await waitFor(() => expect(screen.getByTestId("budget-spent")).toHaveTextContent("0.00013"));
    // Exact decimal strings: a float round trip would corrupt them.
    expect(screen.getByTestId("budget-limit")).toHaveTextContent("1.00");
    expect(screen.getByTestId("budget-remaining")).toHaveTextContent("0.99987");
    expect(screen.getByTestId("budget-percent")).toHaveTextContent("0.01");
    expect(screen.getByTestId("budget-progress")).toBeInTheDocument();
    // The owner reading a percentage is the person who wants to know that crossing it reaches
    // them without their having to come back and look.
    expect(screen.getByTestId("budget-alert-note")).toHaveTextContent(
      /budget\.threshold_crossed/,
    );
  });

  it("distinguishes over-budget-warning from actively-blocking", async () => {
    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(
          status({
            spent: "5",
            limit_amount: "1",
            remaining: "0",
            percent_used: "500.00",
            action: "warn",
            exceeded: true,
          }),
        ),
      ),
    );

    const { unmount } = renderCard("owner");
    await waitFor(() => expect(screen.getByText("Over budget")).toBeInTheDocument());
    // A warning posture must not claim runs are being refused.
    expect(screen.queryByTestId("budget-blocked-notice")).toBeNull();
    unmount();

    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(
          status({
            spent: "5",
            limit_amount: "1",
            remaining: "0",
            percent_used: "500.00",
            action: "block",
            exceeded: true,
            blocked: true,
          }),
        ),
      ),
    );

    renderCard("owner");
    // Blocking is an active incident for everyone using the org, so it is stated up front.
    const notice = await screen.findByTestId("budget-blocked-notice");
    expect(notice).toHaveAttribute("role", "alert");
    expect(notice).toHaveTextContent("New runs are being refused");
    expect(screen.getByText("Blocking new runs")).toBeInTheDocument();
  });

  it("saves a budget with the chosen action", async () => {
    renderCard("owner");
    await waitFor(() => expect(screen.getByTestId("budget-save")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByTestId("budget-limit-input"), "250.50");
    await user.click(screen.getByTestId("budget-action-trigger"));
    await user.click(screen.getByTestId("budget-action-block"));
    await user.click(screen.getByTestId("budget-save"));

    await waitFor(() =>
      expect(puts).toEqual([{ limit_amount: "250.50", action: "block" }]),
    );
  });

  it("pre-fills the form from the current budget", async () => {
    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(
          status({ limit_amount: "42", action: "block", remaining: "42", percent_used: "0.00" }),
        ),
      ),
    );

    renderCard("owner");

    // Editing starts from the current value rather than an empty field to retype.
    await waitFor(() =>
      expect(screen.getByTestId("budget-limit-input")).toHaveValue("42"),
    );
    expect(screen.getByTestId("budget-action-trigger")).toHaveTextContent("Block new runs");
  });

  it("removes a budget", async () => {
    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(status({ limit_amount: "10", action: "warn", remaining: "10", percent_used: "0.00" })),
      ),
    );

    renderCard("owner");
    await waitFor(() => expect(screen.getByTestId("budget-clear")).toBeInTheDocument());

    await userEvent.setup().click(screen.getByTestId("budget-clear"));

    await waitFor(() => expect(deletes).toBe(1));
  });

  it("shows the standing to a member but no controls", async () => {
    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(status({ limit_amount: "10", action: "block", remaining: "4", percent_used: "60.00", spent: "6" })),
      ),
    );

    renderCard("member");

    // Readable: someone about to be refused should be able to see why...
    await waitFor(() => expect(screen.getByTestId("budget-spent")).toHaveTextContent("6"));
    // ...but a spend ceiling is an owner's control, so the form is absent from the DOM.
    expect(screen.queryByTestId("budget-save")).toBeNull();
    expect(screen.queryByTestId("budget-clear")).toBeNull();
    expect(screen.queryByTestId("budget-limit-input")).toBeNull();
  });

  it("surfaces a failed save without losing the entered value", async () => {
    server.use(
      http.put(`${BASE}/budget`, () =>
        HttpResponse.json(
          { error: { code: "validation_error", message: "limit must be >= 0", details: {} } },
          { status: 422 },
        ),
      ),
    );

    renderCard("owner");
    await waitFor(() => expect(screen.getByTestId("budget-save")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByTestId("budget-limit-input"), "-5");
    await user.click(screen.getByTestId("budget-save"));

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toHaveTextContent("limit must be >= 0"),
    );
    expect(screen.getByTestId("budget-limit-input")).toHaveValue("-5");
  });

  it("surfaces a failed read with a retry", async () => {
    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom", details: {} } },
          { status: 500 },
        ),
      ),
    );

    renderCard("owner");

    await waitFor(() => expect(screen.getByTestId("error-message")).toHaveTextContent("boom"));
    expect(screen.queryByTestId("budget-spent")).toBeNull();
  });

  it("has no axe violations in the blocking state", async () => {
    server.use(
      http.get(`${BASE}/budget`, () =>
        HttpResponse.json(
          status({
            spent: "5",
            limit_amount: "1",
            remaining: "0",
            percent_used: "500.00",
            action: "block",
            exceeded: true,
            blocked: true,
          }),
        ),
      ),
    );

    const { container } = renderCard("owner");
    await waitFor(() => expect(screen.getByTestId("budget-blocked-notice")).toBeInTheDocument());

    const results = await axe(container, AXE_OPTIONS);
    expect(results).toHaveNoViolations();
  });
});
