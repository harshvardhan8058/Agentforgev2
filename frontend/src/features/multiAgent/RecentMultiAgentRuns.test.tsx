// @vitest-environment jsdom
import { describe, it, expect, vi, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { RecentMultiAgentRuns } from "./RecentMultiAgentRuns";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderRuns(
  onSelect = vi.fn(),
  selectedRunId: string | null = null,
): ReturnType<typeof vi.fn> {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <SessionContext.Provider value={makeSession("member")}>
        <RecentMultiAgentRuns selectedRunId={selectedRunId} onSelect={onSelect} />
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
  return onSelect;
}

function summary(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "run-1",
    conversation_id: "conv-1",
    task: "Draft a briefing on the Q3 incident",
    status: "terminated",
    termination_reason: "completed",
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

/**
 * A run could only be fetched by an id the caller already held, so a finished
 * collaboration was unreachable once its id left the screen.
 */
describe("RecentMultiAgentRuns", () => {
  it("leads each row with the task, not the id", async () => {
    // A UUID says nothing about what was asked.
    server.use(
      http.get(`${BASE}/multi-agent/runs`, () => HttpResponse.json([summary()])),
    );

    renderRuns();

    expect(
      await screen.findByText("Draft a briefing on the Q3 incident"),
    ).toBeInTheDocument();
  });

  it("shows the status and how the run ended", async () => {
    server.use(
      http.get(`${BASE}/multi-agent/runs`, () => HttpResponse.json([summary()])),
    );

    renderRuns();

    await waitFor(() => expect(screen.getByText("terminated")).toBeInTheDocument());
    expect(screen.getByText("completed")).toBeInTheDocument();
  });

  it("renders a paused run's status readably", async () => {
    // `awaiting_approval` is the status worth noticing, so it must not read as a token.
    server.use(
      http.get(`${BASE}/multi-agent/runs`, () =>
        HttpResponse.json([
          summary({ status: "awaiting_approval", termination_reason: null }),
        ]),
      ),
    );

    renderRuns();

    expect(await screen.findByText("awaiting approval")).toBeInTheDocument();
  });

  it("reports the chosen run to its parent", async () => {
    server.use(
      http.get(`${BASE}/multi-agent/runs`, () => HttpResponse.json([summary()])),
    );
    const onSelect = renderRuns();

    await userEvent.click(await screen.findByTestId("multi-run-row-run-1"));

    expect(onSelect).toHaveBeenCalledWith("run-1");
  });

  it("marks the selected run as pressed", async () => {
    server.use(
      http.get(`${BASE}/multi-agent/runs`, () => HttpResponse.json([summary()])),
    );

    renderRuns(vi.fn(), "run-1");

    const row = await screen.findByTestId("multi-run-row-run-1");
    expect(row).toHaveAttribute("aria-pressed", "true");
  });

  it("shows an empty state when no runs exist", async () => {
    server.use(http.get(`${BASE}/multi-agent/runs`, () => HttpResponse.json([])));

    renderRuns();

    await waitFor(() =>
      expect(screen.getByTestId("multi-runs-empty")).toBeInTheDocument(),
    );
  });

  it("surfaces a listing failure", async () => {
    server.use(
      http.get(`${BASE}/multi-agent/runs`, () =>
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
