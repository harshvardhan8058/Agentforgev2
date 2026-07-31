// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { RecentAgentRuns } from "./RecentAgentRuns";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderRuns(): void {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionContext.Provider value={makeSession("member")}>
        <RecentAgentRuns />
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

function summary(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "run-1",
    created_at: new Date().toISOString(),
    step_count: 4,
    tool_call_count: 1,
    ...overrides,
  };
}

/**
 * A trace could only be fetched by a run id the caller already held, so a finished run
 * was unreachable the moment its id left the screen. This list is what makes a past run
 * addressable, so the behaviour that matters is that its rows resolve to a real trace.
 */
describe("RecentAgentRuns", () => {
  it("lists a run with its step and tool-call counts", async () => {
    server.use(
      http.get(`${BASE}/agent/runs`, () => HttpResponse.json([summary()])),
    );

    renderRuns();

    await waitFor(() =>
      expect(screen.getByTestId("agent-runs-list")).toBeInTheDocument(),
    );
    expect(screen.getByText("4 steps")).toBeInTheDocument();
    expect(screen.getByText("1 tool call")).toBeInTheDocument();
  });

  it("omits the tool-call badge when there were none", async () => {
    // A "0 tool calls" badge is noise; absence is the clearer signal.
    server.use(
      http.get(`${BASE}/agent/runs`, () =>
        HttpResponse.json([summary({ tool_call_count: 0 })]),
      ),
    );

    renderRuns();

    await waitFor(() => expect(screen.getByText("4 steps")).toBeInTheDocument());
    expect(screen.queryByText(/tool call/)).not.toBeInTheDocument();
  });

  it("loads that run's trace when a row is opened", async () => {
    let traceRequested: string | null = null;
    server.use(
      http.get(`${BASE}/agent/runs`, () => HttpResponse.json([summary()])),
      http.get(`${BASE}/agent/runs/:runId/trace`, ({ params }) => {
        traceRequested = String(params.runId);
        return HttpResponse.json({
          run_id: traceRequested,
          entries: [{ ordinal: 0, step_type: "reason", detail: {} }],
        });
      }),
    );

    renderRuns();
    await userEvent.click(await screen.findByTestId("agent-run-row-run-1"));

    await waitFor(() => expect(traceRequested).toBe("run-1"));
    expect(screen.getByTestId("agent-run-trace-run-1")).toBeInTheDocument();
  });

  it("collapses an open row again", async () => {
    server.use(
      http.get(`${BASE}/agent/runs`, () => HttpResponse.json([summary()])),
      http.get(`${BASE}/agent/runs/:runId/trace`, () =>
        HttpResponse.json({ run_id: "run-1", entries: [] }),
      ),
    );

    renderRuns();
    const row = await screen.findByTestId("agent-run-row-run-1");

    await userEvent.click(row);
    expect(screen.getByTestId("agent-run-trace-run-1")).toBeInTheDocument();

    await userEvent.click(row);
    expect(screen.queryByTestId("agent-run-trace-run-1")).not.toBeInTheDocument();
  });

  it("reports expansion state assistively", async () => {
    server.use(
      http.get(`${BASE}/agent/runs`, () => HttpResponse.json([summary()])),
      http.get(`${BASE}/agent/runs/:runId/trace`, () =>
        HttpResponse.json({ run_id: "run-1", entries: [] }),
      ),
    );

    renderRuns();
    const row = await screen.findByTestId("agent-run-row-run-1");

    expect(row).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
  });

  it("shows an empty state when no runs exist", async () => {
    server.use(http.get(`${BASE}/agent/runs`, () => HttpResponse.json([])));

    renderRuns();

    await waitFor(() =>
      expect(screen.getByTestId("agent-runs-empty")).toBeInTheDocument(),
    );
  });

  it("surfaces a listing failure", async () => {
    server.use(
      http.get(`${BASE}/agent/runs`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "Boom.", details: {} } },
          { status: 500 },
        ),
      ),
    );

    renderRuns();

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toBeInTheDocument(),
    );
  });
});
