// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { GettingStarted } from "./GettingStarted";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";

function usageReport(totalTokens: number) {
  return {
    org_id: "org-1",
    start: null,
    end: null,
    total_tokens: totalTokens,
    total_cost: "0",
    by_provider: [],
    by_model: [],
    by_user: [],
  };
}

/** Every signal empty: a brand-new workspace. */
const server = setupServer(
  http.get(`${BASE}/documents`, () => HttpResponse.json([])),
  http.get(`${BASE}/prompts`, () => HttpResponse.json([])),
  http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([])),
  http.get(`${BASE}/orgs/:orgId/api-keys`, () => HttpResponse.json([])),
  http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(usageReport(0))),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderChecklist(role: Role = "owner"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeSession(role)}>
        <MemoryRouter>
          <GettingStarted />
        </MemoryRouter>
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

/**
 * `GettingStarted` — a guided activation path whose completion is derived from
 * real workspace data, never from local flags.
 */
describe("GettingStarted (MSW)", () => {
  it("marks every step incomplete for a brand-new workspace", async () => {
    renderChecklist("owner");
    await waitFor(() => expect(screen.getByTestId("getting-started")).toBeInTheDocument());

    expect(screen.getByTestId("getting-started-step-upload-document")).toHaveAttribute(
      "data-done",
      "false",
    );
    expect(screen.getByTestId("getting-started-progress").textContent).toContain("0 of");
  });

  it("derives completion from real API data", async () => {
    server.use(
      http.get(`${BASE}/documents`, () => HttpResponse.json([{ document_id: "d1" }])),
      http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(usageReport(2500))),
    );

    renderChecklist("owner");
    await waitFor(() => expect(screen.getByTestId("getting-started")).toBeInTheDocument());

    // Uploading a document and recording usage complete three of the steps.
    expect(screen.getByTestId("getting-started-step-upload-document")).toHaveAttribute(
      "data-done",
      "true",
    );
    expect(screen.getByTestId("getting-started-step-run-query")).toHaveAttribute(
      "data-done",
      "true",
    );
    // Untouched capabilities stay open.
    expect(screen.getByTestId("getting-started-step-save-prompt")).toHaveAttribute(
      "data-done",
      "false",
    );
  });

  it("collapses to a single confirmation once everything is done", async () => {
    server.use(
      http.get(`${BASE}/documents`, () => HttpResponse.json([{ document_id: "d1" }])),
      http.get(`${BASE}/prompts`, () => HttpResponse.json(["welcome"])),
      http.get(`${BASE}/evaluations/datasets`, () => HttpResponse.json([{ name: "golden" }])),
      http.get(`${BASE}/orgs/:orgId/api-keys`, () => HttpResponse.json([{ key_id: "k1" }])),
      http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(usageReport(2500))),
    );

    renderChecklist("owner");
    await waitFor(() =>
      expect(screen.getByTestId("getting-started-complete")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("getting-started")).toBeNull();
  });

  it("renders nothing for a viewer, whose role can perform no step", () => {
    // viewer = {read} only, so every step is filtered out and the checklist
    // must disappear entirely rather than show unreachable actions.
    renderChecklist("viewer");
    expect(screen.queryByTestId("getting-started")).toBeNull();
    expect(screen.queryByTestId("getting-started-loading")).toBeNull();
    expect(screen.queryByTestId("getting-started-complete")).toBeNull();
  });

  it("omits key management for a member but keeps the steps they can do", async () => {
    renderChecklist("member");
    await waitFor(() => expect(screen.getByTestId("getting-started")).toBeInTheDocument());

    // member = read + run_agents + ingest_documents (no manage_api_keys).
    expect(screen.getByTestId("getting-started-step-upload-document")).toBeInTheDocument();
    expect(screen.getByTestId("getting-started-step-run-query")).toBeInTheDocument();
    expect(screen.queryByTestId("getting-started-step-issue-api-key")).toBeNull();
    expect(screen.getByTestId("getting-started-progress").textContent).toContain("of 5");
  });

  it("treats a non-array payload as not-yet-done instead of crashing", async () => {
    server.use(http.get(`${BASE}/documents`, () => HttpResponse.json({})));

    renderChecklist("owner");
    await waitFor(() => expect(screen.getByTestId("getting-started")).toBeInTheDocument());
    expect(screen.getByTestId("getting-started-step-upload-document")).toHaveAttribute(
      "data-done",
      "false",
    );
  });
});
