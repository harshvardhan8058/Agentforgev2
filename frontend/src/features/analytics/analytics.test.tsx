// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { SessionContext } from "../../auth/useSession";
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

function renderView(role: Role = "member"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeSession(role)}>
        <UsageDashboardView />
      </SessionContext.Provider>
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
});
