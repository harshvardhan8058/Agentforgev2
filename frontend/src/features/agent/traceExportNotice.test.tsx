// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import type { ReactNode } from "react";

import { TraceView } from "./TraceView";
import { TraceExportNotice } from "./TraceExportNotice";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderIt(ui: ReactNode): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeSession("member")}>
        {ui}
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

function mockStatus(trace_export: Record<string, unknown>): void {
  server.use(
    http.get(`${BASE}/observability/status`, () => HttpResponse.json({ trace_export })),
  );
}

function mockTrace(): void {
  server.use(
    http.get(`${BASE}/agent/runs/:run_id/trace`, () =>
      HttpResponse.json({
        run_id: "run-1",
        entries: [{ ordinal: 0, step_type: "reason" }],
      }),
    ),
  );
}

/**
 * Trace export status (v1.1 "trace export polish").
 *
 * Traces are always recorded; export depends on a server credential. Without this
 * notice an unexported trace and a trace that has not yet reached an external
 * dashboard look identical, which is the ambiguity the roadmap item names.
 */
describe("TraceExportNotice (MSW)", () => {
  it("states that export is off for the keyless default", async () => {
    mockStatus({ enabled: false, exporter: "noop", destination: null });

    renderIt(<TraceExportNotice />);

    const notice = await screen.findByTestId("trace-export-notice");
    expect(notice).toHaveAttribute("data-export-enabled", "false");
    expect(notice).toHaveTextContent("external trace export is off");
  });

  it("names the destination when export is configured", async () => {
    mockStatus({ enabled: true, exporter: "langsmith", destination: "acme-prod" });

    renderIt(<TraceExportNotice />);

    const notice = await screen.findByTestId("trace-export-notice");
    expect(notice).toHaveAttribute("data-export-enabled", "true");
    expect(notice).toHaveTextContent("exported to LangSmith");
    expect(notice).toHaveTextContent("acme-prod");
  });

  it("shows an unknown exporter's identifier verbatim rather than guessing", async () => {
    mockStatus({ enabled: true, exporter: "vendor-x", destination: null });

    renderIt(<TraceExportNotice />);

    expect(await screen.findByTestId("trace-export-notice")).toHaveTextContent(
      "exported to vendor-x",
    );
  });

  it("renders nothing when the status call fails, leaving the trace readable", async () => {
    // Contextual information beside a trace that rendered fine: an error banner here
    // would report a problem the user did not ask about and cannot act on.
    server.use(
      http.get(`${BASE}/observability/status`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom", details: {} } },
          { status: 500 },
        ),
      ),
    );
    mockTrace();

    renderIt(<TraceView runId="run-1" />);

    await waitFor(() =>
      expect(screen.getByTestId("trace-entry-0")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("trace-export-notice")).toBeNull();
    expect(screen.queryByTestId("error-banner")).toBeNull();
  });

  it("appears beneath a rendered trace timeline", async () => {
    mockStatus({ enabled: false, exporter: "noop", destination: null });
    mockTrace();

    renderIt(<TraceView runId="run-1" />);

    await waitFor(() =>
      expect(screen.getByTestId("trace-entry-0")).toBeInTheDocument(),
    );
    expect(await screen.findByTestId("trace-export-notice")).toBeInTheDocument();
  });
});
