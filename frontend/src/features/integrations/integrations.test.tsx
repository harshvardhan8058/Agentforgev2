// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { IntegrationsView } from "./IntegrationsView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";

/** A usage report with only the fields this view reads populated. */
function usageReport(byProvider: { key: string; total_tokens: number }[]) {
  return {
    org_id: "org-1",
    start: null,
    end: null,
    total_tokens: byProvider.reduce((n, p) => n + p.total_tokens, 0),
    total_cost: "0",
    by_provider: byProvider.map((p) => ({ ...p, total_cost: "0" })),
    by_model: [],
    by_user: [],
  };
}

const server = setupServer(
  // Sensible defaults; individual tests override what they assert on.
  http.get(`${BASE}/integrations/status`, () => HttpResponse.json({ integrations: [] })),
  http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(usageReport([]))),
);

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
        <IntegrationsView />
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

/**
 * `IntegrationsView` — surfaces `GET /integrations/status` (which previously had
 * no frontend route at all) plus the language-model provider actually serving
 * traffic, derived from the usage report's `by_provider` breakdown.
 */
describe("IntegrationsView (MSW)", () => {
  it("lists each connector with its enabled state", async () => {
    server.use(
      http.get(`${BASE}/integrations/status`, () =>
        HttpResponse.json({
          integrations: [
            { name: "slack", enabled: true },
            { name: "gmail", enabled: false },
            { name: "google_drive", enabled: false },
            { name: "github", enabled: false },
          ],
        }),
      ),
    );

    renderView();
    await waitFor(() => expect(screen.getByTestId("connectors-list")).toBeInTheDocument());

    // Friendly labels, not raw backend keys.
    expect(screen.getByTestId("connector-name-google_drive").textContent).toBe("Google Drive");

    // Enabled state is exposed both visually and as a stable data attribute.
    expect(screen.getByTestId("connector-slack")).toHaveAttribute("data-enabled", "true");
    expect(screen.getByTestId("connector-gmail")).toHaveAttribute("data-enabled", "false");
    expect(screen.getByTestId("connector-state-slack").textContent).toContain("Enabled");
    expect(screen.getByTestId("connector-state-gmail").textContent).toContain("Not configured");
  });

  it("renders an unknown connector name rather than hiding it", async () => {
    server.use(
      http.get(`${BASE}/integrations/status`, () =>
        HttpResponse.json({ integrations: [{ name: "notion_beta", enabled: false }] }),
      ),
    );

    renderView();
    await waitFor(() =>
      expect(screen.getByTestId("connector-name-notion_beta")).toBeInTheDocument(),
    );
    // Title-cased fallback label so a new backend connector is never invisible.
    expect(screen.getByTestId("connector-name-notion_beta").textContent).toBe("Notion Beta");
  });

  it("renders an empty state when the deployment reports no connectors", async () => {
    renderView();
    await waitFor(() => expect(screen.getByTestId("connectors-empty")).toBeInTheDocument());
  });

  it("explains keyless mode when the fallback provider served traffic", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(usageReport([{ key: "fallback", total_tokens: 1200 }])),
      ),
    );

    renderView();
    await waitFor(() =>
      expect(screen.getByTestId("model-provider-fallback")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("model-provider-fallback").textContent).toContain("GROQ_API_KEY");
    expect(screen.queryByTestId("model-provider-unknown")).toBeNull();
  });

  it("shows the real provider and no fallback notice once one is configured", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(usageReport([{ key: "groq", total_tokens: 500 }])),
      ),
    );

    renderView();
    await waitFor(() => expect(screen.getByTestId("model-provider-groq")).toBeInTheDocument());
    expect(screen.queryByTestId("model-provider-fallback")).toBeNull();
  });

  it("ignores providers with no recorded tokens", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(usageReport([{ key: "fallback", total_tokens: 0 }])),
      ),
    );

    renderView();
    // A zero-token entry is not evidence the provider served anything.
    await waitFor(() => expect(screen.getByTestId("model-provider-unknown")).toBeInTheDocument());
    expect(screen.queryByTestId("model-provider-fallback")).toBeNull();
  });

  it("stays usable when the usage endpoint returns a non-array payload", async () => {
    // The API contract says by_provider is an array; a malformed/mocked body
    // must not crash the page (mirrors the e2e catch-all returning {}).
    server.use(http.get(`${BASE}/analytics/usage`, () => HttpResponse.json({})));

    renderView();
    await waitFor(() => expect(screen.getByTestId("model-provider-unknown")).toBeInTheDocument());
    expect(screen.getByTestId("integrations-view")).toBeInTheDocument();
  });
});
