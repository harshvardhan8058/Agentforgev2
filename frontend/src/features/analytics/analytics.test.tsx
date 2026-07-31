// @vitest-environment jsdom
import {
  describe,
  it,
  expect,
  beforeAll,
  beforeEach,
  afterAll,
  afterEach,
  vi,
} from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { SessionContext } from "../../auth/useSession";
import { ToastProvider } from "../../providers/ToastProvider";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

// Mock the lazy-loaded charting layer with a lightweight stub so the suite
// stays keyless, fast, and deterministic (Monaco/charts are never loaded).
vi.mock("./UsageCharts", () => ({
  default: ({ sections }: { sections: { id: string }[] }) => (
    <div data-testid="usage-charts-stub">{sections.map((s) => s.id).join(",")}</div>
  ),
}));

import { UsageDashboardView } from "./UsageDashboardView";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

/** The pricing configuration the dashboard's `CostRatesPanel` always requests. */
function ratesFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    preset: null,
    available_presets: ["groq-public-2026-07"],
    default_prompt_per_1k: "0.0",
    default_completion_per_1k: "0.0",
    configured: false,
    rates: [],
    ...overrides,
  };
}

// Registered per test (and therefore reset with the rest) so any test may override
// it by declaring its own handler: in MSW the most recently added one wins.
beforeEach(() =>
  server.use(
    http.get(`${BASE}/analytics/cost-rates`, () => HttpResponse.json(ratesFixture())),
    // The dashboard also carries the spend-budget card.
    http.get(`${BASE}/budget`, () =>
      HttpResponse.json({
        period_start: "2026-08-01T00:00:00Z",
        period_end: "2026-09-01T00:00:00Z",
        spent: "0",
        limit_amount: null,
        remaining: null,
        percent_used: null,
        action: null,
        exceeded: false,
        blocked: false,
      }),
    ),
  ),
);

function renderView(role: Role = "member"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          <UsageDashboardView />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function reportFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    org_id: "org-1",
    start: "1970-01-01T00:00:00Z",
    end: "2024-06-01T00:00:00Z",
    total_tokens: 1234,
    total_cost: "12.3456",
    by_provider: [{ key: "openai", total_tokens: 1000, total_cost: "10.0000" }],
    by_model: [{ key: "gpt-4", total_tokens: 900, total_cost: "9.5000" }],
    by_user: [{ key: "user-1", total_tokens: 334, total_cost: "2.8456" }],
    ...overrides,
  };
}

/**
 * Task 22.2 — analytics dashboard.
 * _Requirements: 11.1, 11.2, 11.3, 11.5, 11.6_
 */
describe("UsageDashboardView (MSW)", () => {
  it("displays total_tokens and verbatim total_cost (11.1)", async () => {
    server.use(http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(reportFixture())));

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("analytics-content")).toBeInTheDocument());
    expect(screen.getByTestId("usage-total-tokens").textContent).toBe("1234");
    expect(screen.getByTestId("usage-total-cost").textContent).toBe("12.3456");
  });

  it("adds start/end query params when a range is applied (11.2)", async () => {
    const seen: Array<{ start: string | null; end: string | null }> = [];
    server.use(
      http.get(`${BASE}/analytics/usage`, ({ request }) => {
        const url = new URL(request.url);
        seen.push({ start: url.searchParams.get("start"), end: url.searchParams.get("end") });
        return HttpResponse.json(reportFixture());
      }),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("analytics-content")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByTestId("usage-start"), "2024-01-01T00:00");
    await user.type(screen.getByTestId("usage-end"), "2024-02-01T00:00");
    await user.click(screen.getByTestId("range-apply"));

    await waitFor(() => {
      const last = seen[seen.length - 1];
      expect(last.start).toBe("2024-01-01T00:00");
      expect(last.end).toBe("2024-02-01T00:00");
    });
  });

  it("renders by_provider/by_model/by_user breakdown rows (11.3)", async () => {
    server.use(http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(reportFixture())));

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("analytics-content")).toBeInTheDocument());

    expect(screen.getByTestId("breakdown-by_provider-key-0").textContent).toBe("openai");
    expect(screen.getByTestId("breakdown-by_provider-cost-0").textContent).toBe("10.0000");
    expect(screen.getByTestId("breakdown-by_model-key-0").textContent).toBe("gpt-4");
    expect(screen.getByTestId("breakdown-by_user-key-0").textContent).toBe("user-1");
  });

  it("renders an empty usage state for a no-record range (11.5)", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(
          reportFixture({ total_tokens: 0, by_provider: [], by_model: [], by_user: [] }),
        ),
      ),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("analytics-empty")).toBeInTheDocument());
    expect(screen.queryByTestId("analytics-content")).toBeNull();
  });

  it("isolates one failing breakdown while totals and others still render (11.6)", async () => {
    // A malformed `by_model` entry (null) makes only that breakdown throw.
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(reportFixture({ by_model: [null] })),
      ),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("analytics-content")).toBeInTheDocument());

    // Totals still render verbatim.
    expect(screen.getByTestId("usage-total-cost").textContent).toBe("12.3456");
    // The failing breakdown shows its isolated fallback...
    expect(screen.getByTestId("breakdown-error-by_model")).toBeInTheDocument();
    // ...while the other breakdowns render normally.
    expect(screen.getByTestId("breakdown-by_provider-key-0").textContent).toBe("openai");
    expect(screen.getByTestId("breakdown-by_user-key-0").textContent).toBe("user-1");
  });
  it("shows the effective per-model cost rates and marks overrides", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(reportFixture())),
      http.get(`${BASE}/analytics/cost-rates`, () =>
        HttpResponse.json(
          ratesFixture({
            preset: "groq-public-2026-07",
            configured: true,
            rates: [
              {
                provider: "groq",
                model: "llama-3.1-8b-instant",
                prompt_per_1k: "0.00005",
                completion_per_1k: "0.00008",
                source: "preset",
              },
              {
                provider: "groq",
                model: "llama-3.3-70b-versatile",
                prompt_per_1k: "0.001",
                completion_per_1k: "0.002",
                source: "override",
              },
            ],
          }),
        ),
      ),
    );

    renderView("member");

    await waitFor(() =>
      expect(screen.getByTestId("cost-rates-table")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("cost-rates-preset").textContent).toBe(
      "groq-public-2026-07",
    );
    // Rates are rendered verbatim - an exact decimal string, never a float.
    const priced = screen.getByTestId("cost-rate-groq-llama-3.1-8b-instant");
    expect(priced.textContent).toContain("0.00005");
    expect(priced.textContent).toContain("preset");
    expect(
      screen.getByTestId("cost-rate-groq-llama-3.3-70b-versatile").textContent,
    ).toContain("override");
  });

  it("names the available presets when the deployment prices nothing", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(reportFixture({ cost_rates_configured: false })),
      ),
    );

    renderView("member");

    await waitFor(() =>
      expect(screen.getByTestId("cost-rates-available").textContent).toBe(
        "groq-public-2026-07",
      ),
    );
    expect(screen.queryByTestId("cost-rates-table")).toBeNull();
    // The totals tile independently reports the same fact.
    expect(screen.getByTestId("usage-total-cost-display").textContent).toBe("Not priced");
  });

  it("keeps the usage report readable when the pricing endpoint fails", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(reportFixture())),
      http.get(`${BASE}/analytics/cost-rates`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom", details: {} } },
          { status: 500 },
        ),
      ),
    );

    renderView("member");

    await waitFor(() =>
      expect(screen.getByTestId("analytics-content")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("usage-total-tokens").textContent).toBe("1234");
    await waitFor(() =>
      expect(screen.getByTestId("cost-rates-panel")).toHaveTextContent("boom"),
    );
  });
});
