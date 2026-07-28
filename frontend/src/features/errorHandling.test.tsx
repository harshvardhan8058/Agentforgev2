// @vitest-environment jsdom
/**
 * Task 26.1 — cross-cutting error handling & graceful degradation (MSW).
 *
 * Exercises the status-specific behavior from the design's Error Handling table
 * and the graceful-degradation rules against real feature views wired to MSW:
 *  - 422 validation_error → field errors mapped against form fields (Req 5.3)
 *  - 429 rate_limited      → rate-limit notice + unsubmitted input preserved (Req 5.4)
 *  - 500 internal_error    → generic message, never a stack trace (Req 5.5)
 *  - 502 llm_provider_error→ provider message + submitted input preserved for retry (Req 6.5)
 *  - network failure       → connectivity error + RetryNotice retry action (Req 5.6)
 *  - empty result set      → explicit empty state (Req 6.2)
 *  - NoOp trace            → run data rendered + trace detail unavailable (Req 6.3)
 *  - partial capabilities  → only present capabilities rendered (Req 6.4)
 *  - optional feature off  → views backed by enabled contracts still operate (Req 6.1)
 *
 * _Requirements: 5.3, 5.4, 5.5, 5.6, 6.1, 6.2, 6.3, 6.4, 6.5_
 */
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { RagQueryView } from "./query/RagQueryView";
import { DocumentListView } from "./documents/DocumentListView";
import { GuardrailsView } from "./guardrails/GuardrailsView";
import { TraceView } from "./agent/TraceView";
import { SessionContext } from "../auth/useSession";
import { makeSession } from "../test/renderWithSession";
import { ToastProvider } from "../providers/ToastProvider";
import type { Role } from "../auth/token";
import type { ReactNode } from "react";

const BASE = "http://localhost:8000";
// RagQueryView resolves citation filenames from GET /documents; a default
// empty-corpus handler keeps these error-path tests green (the specific
// DocumentListView test overrides it as needed).
const server = setupServer(
  http.get(`${BASE}/documents`, () => HttpResponse.json([])),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderView(ui: ReactNode, role: Role = "member"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          {ui}
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

async function submitQuery(text = "what is the policy"): Promise<void> {
  const user = userEvent.setup();
  await user.type(screen.getByTestId("query-input"), text);
  await user.click(screen.getByTestId("query-submit"));
}

describe("Cross-cutting error handling (Task 26.1)", () => {
  it("maps 422 validation_error to field errors (5.3)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json(
          {
            error: {
              code: "validation_error",
              message: "The request could not be validated.",
              details: {
                errors: [{ loc: ["body", "query"], msg: "field required" }],
              },
            },
          },
          { status: 422 },
        ),
      ),
    );

    renderView(<RagQueryView />);
    await submitQuery();

    await waitFor(() =>
      expect(screen.getByTestId("query-error")).toBeInTheDocument(),
    );
    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveAttribute("data-kind", "validation");
    const fieldErrors = screen.getByTestId("error-field-errors");
    expect(fieldErrors).toHaveTextContent("query");
    expect(fieldErrors).toHaveTextContent("field required");
    // Answer is withheld while the error is shown.
    expect(screen.queryByTestId("query-answer-card")).toBeNull();
  });

  it("shows a 429 rate-limit notice and preserves unsubmitted input (5.4)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json(
          {
            error: {
              code: "rate_limited",
              message: "Too many requests. Please wait and try again.",
              details: {},
            },
          },
          { status: 429 },
        ),
      ),
    );

    renderView(<RagQueryView />);
    await submitQuery("expensive question");

    await waitFor(() =>
      expect(screen.getByTestId("query-error")).toBeInTheDocument(),
    );
    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveAttribute("data-kind", "rate_limited");
    expect(banner).toHaveTextContent("Too many requests");
    // The Operator's input is preserved so a retry needs no re-entry.
    expect(screen.getByTestId("query-input")).toHaveValue("expensive question");
  });

  it("renders a generic 500 message with no stack trace (5.5)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json(
          {
            error: {
              code: "internal_error",
              message: "An internal error occurred while processing the request.",
              details: {},
            },
          },
          { status: 500 },
        ),
      ),
    );

    renderView(<RagQueryView />);
    await submitQuery();

    await waitFor(() =>
      expect(screen.getByTestId("query-error")).toBeInTheDocument(),
    );
    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveAttribute("data-kind", "server");
    expect(banner).toHaveTextContent("An internal error occurred");
    // No stack/traceback text is ever surfaced.
    expect(banner.textContent ?? "").not.toMatch(/traceback|at \w+\.|\bstack\b/i);
  });

  it("shows a 502 provider message and preserves submitted input for retry (6.5)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json(
          {
            error: {
              code: "llm_provider_error",
              message: "The upstream provider is temporarily unavailable.",
              details: {},
            },
          },
          { status: 502 },
        ),
      ),
    );

    renderView(<RagQueryView />);
    await submitQuery("summarize the report");

    await waitFor(() =>
      expect(screen.getByTestId("query-error")).toBeInTheDocument(),
    );
    const banner = screen.getByTestId("error-banner");
    expect(banner).toHaveAttribute("data-kind", "provider");
    expect(banner).toHaveTextContent("upstream provider");
    // Submitted input is preserved for a retry.
    expect(screen.getByTestId("query-input")).toHaveValue("summarize the report");
  });

  it("shows a connectivity error + RetryNotice on network failure, then retries (5.6)", async () => {
    server.use(
      // First attempt fails at the transport layer (no HTTP response).
      http.post(`${BASE}/query`, () => HttpResponse.error(), { once: true }),
      // The retry succeeds.
      http.post(`${BASE}/query`, () =>
        HttpResponse.json({
          answer: "Recovered answer.",
          grounded: true,
          provider: "openai",
          citations: [],
          flags: [],
        }),
      ),
    );

    renderView(<RagQueryView />);
    await submitQuery("resilient question");

    // Network failure surfaces the connectivity RetryNotice, not a raw banner.
    await waitFor(() =>
      expect(screen.getByTestId("retry-notice")).toBeInTheDocument(),
    );
    // Input preserved across the failure.
    expect(screen.getByTestId("query-input")).toHaveValue("resilient question");

    const user = userEvent.setup();
    await user.click(
      screen.getByTestId("retry-notice").querySelector("button")!,
    );

    // Retry re-submits the preserved input and succeeds.
    await waitFor(() =>
      expect(screen.getByTestId("query-answer-card")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("answer-body")).toHaveTextContent("Recovered answer.");
  });

  it("renders an explicit empty state for an empty result set (6.2)", async () => {
    server.use(http.get(`${BASE}/documents`, () => HttpResponse.json([])));

    renderView(<DocumentListView />);

    await waitFor(() =>
      expect(screen.getByTestId("empty-state")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("documents-list")).toBeNull();
  });

  it("renders run data and marks trace detail unavailable for a NoOp trace (6.3)", async () => {
    server.use(
      http.get(`${BASE}/agent/runs/:run_id/trace`, () =>
        HttpResponse.json({ run_id: "run-1", entries: [] }),
      ),
    );

    renderView(<TraceView runId="run-1" />);

    await waitFor(() =>
      expect(screen.getByTestId("trace-detail-unavailable")).toBeInTheDocument(),
    );
    // Not an error surface — degrades gracefully.
    expect(screen.queryByTestId("error-banner")).toBeNull();
    expect(screen.queryByTestId("trace-not-found")).toBeNull();
  });

  it("renders only the capabilities present in a partial response (6.4)", async () => {
    // Response omits the optional `flags` and `citations` capabilities entirely.
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json({
          answer: "A plain grounded answer.",
          grounded: true,
          provider: "anthropic",
        }),
      ),
    );

    renderView(<RagQueryView />);
    await submitQuery("partial");

    await waitFor(() =>
      expect(screen.getByTestId("query-answer-card")).toBeInTheDocument(),
    );
    // The present capabilities render…
    expect(screen.getByTestId("answer-provider")).toHaveTextContent("anthropic");
    expect(screen.getByTestId("answer-body")).toHaveTextContent(
      "A plain grounded answer.",
    );
    // …and the absent optional capabilities are simply not rendered.
    expect(screen.queryByTestId("answer-flags")).toBeNull();
    expect(screen.queryByTestId("citation-list")).toBeNull();
  });

  it("keeps a view operational when an optional feature is disabled (6.1)", async () => {
    // Guardrails "disabled": config is empty, but the evaluate contract still works.
    server.use(
      http.get(`${BASE}/guardrails/config`, () =>
        HttpResponse.json({ guardrails: [] }),
      ),
      http.post(`${BASE}/guardrails/evaluate`, () =>
        HttpResponse.json({ decision: "allow", flags: [], reason: null }),
      ),
    );

    renderView(<GuardrailsView />);

    // Empty config is surfaced explicitly…
    await waitFor(() =>
      expect(screen.getByTestId("guardrails-empty")).toBeInTheDocument(),
    );

    // …yet the evaluate capability (an enabled contract) remains fully operational.
    const user = userEvent.setup();
    await user.type(screen.getByTestId("guardrail-content"), "check me");
    await user.click(screen.getByTestId("evaluate-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("evaluate-result")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("decision-badge")).toHaveTextContent("allow");
  });
});
