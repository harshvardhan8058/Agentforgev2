// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { SingleAgentRunView } from "./SingleAgentRunView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import { renderSseFrame } from "../../api/sse/parse";
import { __resetTokenStoreForTests } from "../../auth/tokenStore";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  __resetTokenStoreForTests();
});
afterAll(() => server.close());

/** Build a simulated `text/event-stream` response from raw SSE frames. */
function sseResponse(frames: string[], keepOpen = false): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      if (!keepOpen) controller.close();
    },
  });
  return new HttpResponse(stream, {
    headers: { "Content-Type": "text/event-stream" },
  });
}

function renderView(role: Role = "member"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          <SingleAgentRunView />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/**
 * Task 19.1 — single-agent run + trace (MSW SSE).
 * _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_
 */
describe("SingleAgentRunView (MSW SSE)", () => {
  it("renders streamed events in order and the completion answer + citations (9.1, 9.2)", async () => {
    server.use(
      http.post(`${BASE}/agent/stream`, () =>
        sseResponse([
          renderSseFrame("step", { sequence: 0, description: "thinking" }),
          renderSseFrame("delta", { sequence: 1, text: "Hello " }),
          renderSseFrame("delta", { sequence: 2, text: "world [1]" }),
          renderSseFrame("completion", {
            sequence: 3,
            run_id: "run-1",
            answer: "Hello world [1]",
            termination_reason: "final-answer",
            citations: [{ document_id: "doc-1", chunk_id: "chunk-1" }],
          }),
        ]),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("agent-message"), "hi");
    await user.click(screen.getByTestId("agent-run-stream"));

    await waitFor(() =>
      expect(screen.getByTestId("stream-answer")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("stream-answer")).toHaveTextContent("Hello world");
    expect(screen.getByTestId("stream-termination-reason")).toHaveTextContent(
      "final-answer",
    );
    // The inline [1] marker resolved to a citation link.
    expect(screen.getByTestId("citation-1")).toBeInTheDocument();
    expect(screen.getByTestId("agent-citations")).toHaveTextContent("doc-1");
  });

  it("renders the error detail on an error terminal (9.3)", async () => {
    server.use(
      http.post(`${BASE}/agent/stream`, () =>
        sseResponse([
          renderSseFrame("delta", { sequence: 0, text: "partial" }),
          renderSseFrame("error", {
            sequence: 1,
            message: "The provider timed out.",
            error_type: "provider_error",
          }),
        ]),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("agent-message"), "hi");
    await user.click(screen.getByTestId("agent-run-stream"));

    await waitFor(() =>
      expect(screen.getByTestId("stream-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("stream-error")).toHaveTextContent(
      "The provider timed out.",
    );
  });

  it("shows answer + termination_reason + citations for a non-streaming run (9.4)", async () => {
    server.use(
      http.post(`${BASE}/agent/run`, () =>
        HttpResponse.json({
          run_id: "run-2",
          conversation_id: "conv-2",
          answer: "The non-streamed answer [1].",
          termination_reason: "final-answer",
          citations: [{ document_id: "doc-9", chunk_id: "chunk-9" }],
          flags: [],
        }),
      ),
      // Trace is fetched once the run completes (run_id captured).
      http.get(`${BASE}/agent/runs/run-2/trace`, () =>
        HttpResponse.json({ run_id: "run-2", entries: [] }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("agent-message"), "hi");
    await user.click(screen.getByTestId("agent-run"));

    await waitFor(() =>
      expect(screen.getByTestId("run-result-card")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("run-answer")).toHaveTextContent(
      "The non-streamed answer",
    );
    expect(screen.getByTestId("run-termination-reason")).toHaveTextContent(
      "final-answer",
    );
    expect(screen.getByTestId("agent-citations")).toHaveTextContent("doc-9");
  });

  it("renders the trace ordered by ordinal (9.5)", async () => {
    server.use(
      http.post(`${BASE}/agent/run`, () =>
        HttpResponse.json({
          run_id: "run-3",
          conversation_id: "conv-3",
          answer: "answer",
          termination_reason: "final-answer",
          citations: [],
          flags: [],
        }),
      ),
      http.get(`${BASE}/agent/runs/run-3/trace`, () =>
        HttpResponse.json({
          run_id: "run-3",
          // Deliberately out of order — the timeline must sort by ordinal.
          entries: [
            { ordinal: 2, step_type: "act", tool_name: "search" },
            { ordinal: 0, step_type: "plan" },
            { ordinal: 1, step_type: "observe" },
          ],
        }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("agent-message"), "hi");
    await user.click(screen.getByTestId("agent-run"));

    await waitFor(() =>
      expect(screen.getByTestId("trace-timeline")).toBeInTheDocument(),
    );
    const items = screen.getAllByTestId(/^trace-entry-/);
    const ordinals = items.map((el) => el.getAttribute("data-ordinal"));
    expect(ordinals).toEqual(["0", "1", "2"]);
  });

  it("presents the trace as not found on 404 (9.6)", async () => {
    server.use(
      http.post(`${BASE}/agent/run`, () =>
        HttpResponse.json({
          run_id: "run-404",
          conversation_id: "conv-404",
          answer: "answer",
          termination_reason: "final-answer",
          citations: [],
          flags: [],
        }),
      ),
      http.get(`${BASE}/agent/runs/run-404/trace`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Run not found.", details: {} } },
          { status: 404 },
        ),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("agent-message"), "hi");
    await user.click(screen.getByTestId("agent-run"));

    await waitFor(() =>
      expect(screen.getByTestId("trace-not-found")).toBeInTheDocument(),
    );
  });

  it("cancel aborts the open stream (9.7)", async () => {
    server.use(
      http.post(`${BASE}/agent/stream`, () =>
        // Emit one delta then keep the stream open so cancel has something to abort.
        sseResponse([renderSseFrame("delta", { sequence: 0, text: "streaming…" })], true),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("agent-message"), "hi");
    await user.click(screen.getByTestId("agent-run-stream"));

    // Stream is open.
    await waitFor(() =>
      expect(screen.getByTestId("streaming-indicator")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("agent-cancel"));

    // Cancel closes the client subscription — no completion, no streaming badge.
    await waitFor(() =>
      expect(screen.queryByTestId("streaming-indicator")).toBeNull(),
    );
    expect(screen.queryByTestId("stream-answer")).toBeNull();
  });

  it("omits run controls when the role lacks run_agents (4.2)", () => {
    renderView("viewer");
    expect(screen.getByTestId("agent-view")).toBeInTheDocument();
    expect(screen.queryByTestId("agent-form-card")).toBeNull();
    expect(screen.queryByTestId("agent-run-stream")).toBeNull();
  });
});
