// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { MultiAgentRunView } from "./MultiAgentRunView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import { ConversationProvider } from "../conversations/ConversationContext";
import { renderSseFrame } from "../../api/sse/parse";
import { __resetTokenStoreForTests } from "../../auth/tokenStore";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
// The run page now also lists past runs, so every render calls
// `GET /multi-agent/runs`. Registered as a default handler for the same reason as above.
const server = setupServer(
  http.get(`${BASE}/multi-agent/runs`, () => HttpResponse.json([])),
);

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
        <ConversationProvider>
          <SessionContext.Provider value={makeSession(role)}>
            <MultiAgentRunView />
          </SessionContext.Provider>
        </ConversationProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const startHandler = () =>
  http.post(`${BASE}/multi-agent/runs`, () =>
    HttpResponse.json(
      {
        run_id: "mrun-1",
        conversation_id: "mconv-1",
        status: "running",
        flags: [],
      },
      { status: 201 },
    ),
  );

async function startRun(): Promise<ReturnType<typeof userEvent.setup>> {
  const user = userEvent.setup();
  await user.type(screen.getByTestId("multi-task"), "draft a brief");
  await user.click(screen.getByTestId("multi-start"));
  await waitFor(() =>
    expect(screen.getByTestId("multi-run-summary")).toBeInTheDocument(),
  );
  return user;
}

/**
 * Task 21.1 — multi-agent run + approval (MSW SSE).
 * _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8_
 */
describe("MultiAgentRunView (MSW SSE)", () => {
  it("shows run_id / conversation_id / status on start (10.1)", async () => {
    server.use(startHandler());
    renderView("member");
    await startRun();

    expect(screen.getByTestId("multi-run-id")).toHaveTextContent("mrun-1");
    expect(screen.getByTestId("multi-conversation-id")).toHaveTextContent(
      "mconv-1",
    );
    expect(screen.getByTestId("multi-status")).toHaveTextContent("running");
  });

  it("attributes events to role_id and orders them by sequence (10.2)", async () => {
    server.use(
      startHandler(),
      http.post(`${BASE}/multi-agent/runs/mrun-1/stream`, () =>
        // Deliberately out of receive order — the reducer sorts by sequence.
        sseResponse([
          renderSseFrame("agent_started", { sequence: 0, role_id: "planner" }),
          renderSseFrame("research", { sequence: 2, role_id: "researcher", content: "found" }),
          renderSseFrame("plan", { sequence: 1, role_id: "planner", steps: ["a", "b"] }),
          renderSseFrame("draft", { sequence: 3, role_id: "writer", content: "draft" }),
          renderSseFrame("critic_feedback", { sequence: 4, role_id: "critic", comments: "ok" }),
        ]),
      ),
    );
    renderView("member");
    const user = await startRun();
    await user.click(screen.getByTestId("multi-stream-open"));

    await waitFor(() =>
      expect(screen.getByTestId("multi-event-log")).toBeInTheDocument(),
    );

    // Ordered by sequence.
    const items = within(screen.getByTestId("multi-event-log")).getAllByRole(
      "listitem",
    );
    const seqs = items.map((el) => el.getAttribute("data-sequence"));
    expect(seqs).toEqual(["0", "1", "2", "3", "4"]);

    // Role-attributed panes.
    expect(screen.getByTestId("role-pane-planner")).toBeInTheDocument();
    expect(screen.getByTestId("role-pane-researcher")).toBeInTheDocument();
    expect(screen.getByTestId("role-pane-writer")).toBeInTheDocument();
    expect(screen.getByTestId("role-pane-critic")).toBeInTheDocument();
  });

  it("renders the approval checkpoint with approve/reject/edit (10.3)", async () => {
    server.use(
      startHandler(),
      http.post(`${BASE}/multi-agent/runs/mrun-1/stream`, () =>
        sseResponse([
          renderSseFrame("agent_started", { sequence: 0, role_id: "planner" }),
          renderSseFrame("approval_required", {
            sequence: 1,
            run_id: "mrun-1",
            checkpoint: "Approve the plan before drafting?",
          }),
        ]),
      ),
    );
    renderView("member");
    const user = await startRun();
    await user.click(screen.getByTestId("multi-stream-open"));

    await waitFor(() =>
      expect(screen.getByTestId("approval-panel")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("approval-checkpoint")).toHaveTextContent(
      "Approve the plan",
    );
    expect(screen.getByTestId("approval-approve")).toBeInTheDocument();
    expect(screen.getByTestId("approval-reject")).toBeInTheDocument();
    expect(screen.getByTestId("approval-edit")).toBeInTheDocument();
  });

  it("submits an approval decision and shows the returned status + reason (10.4)", async () => {
    server.use(
      startHandler(),
      http.post(`${BASE}/multi-agent/runs/mrun-1/stream`, () =>
        sseResponse([
          renderSseFrame("approval_required", {
            sequence: 0,
            run_id: "mrun-1",
            checkpoint: "Approve?",
          }),
        ]),
      ),
      http.post(`${BASE}/multi-agent/runs/mrun-1/approval`, () =>
        HttpResponse.json({
          run_id: "mrun-1",
          status: "terminated",
          termination_reason: "completed",
        }),
      ),
    );
    renderView("member");
    const user = await startRun();
    await user.click(screen.getByTestId("multi-stream-open"));
    await waitFor(() =>
      expect(screen.getByTestId("approval-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("approval-approve"));

    await waitFor(() =>
      expect(screen.getByTestId("approval-status")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("approval-status")).toHaveTextContent("terminated");
    expect(screen.getByTestId("approval-termination-reason")).toHaveTextContent(
      "completed",
    );
  });

  it("renders final output + citations on completion (10.5)", async () => {
    server.use(
      startHandler(),
      http.post(`${BASE}/multi-agent/runs/mrun-1/stream`, () =>
        sseResponse([
          renderSseFrame("agent_started", { sequence: 0, role_id: "planner" }),
          renderSseFrame("completion", {
            sequence: 1,
            content: "The final briefing [1].",
            termination_reason: "completed",
            citations: [{ document_id: "doc-7", chunk_id: "chunk-7" }],
          }),
        ]),
      ),
    );
    renderView("member");
    const user = await startRun();
    await user.click(screen.getByTestId("multi-stream-open"));

    await waitFor(() =>
      expect(screen.getByTestId("multi-final-output")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("multi-final-output")).toHaveTextContent(
      "The final briefing",
    );
    expect(screen.getByTestId("multi-termination-reason")).toHaveTextContent(
      "completed",
    );
    expect(screen.getByTestId("multi-citations")).toHaveTextContent("doc-7");
    // The inline [1] marker resolved to a citation link.
    expect(screen.getByTestId("citation-1")).toBeInTheDocument();
  });

  it("shows the persisted run result + role-attributed trace (10.6)", async () => {
    server.use(
      startHandler(),
      http.get(`${BASE}/multi-agent/runs/mrun-1`, () =>
        HttpResponse.json({
          run_id: "mrun-1",
          status: "terminated",
          termination_reason: "completed",
          final_output: {
            content: "Persisted final output.",
            citations: [{ document_id: "doc-3", chunk_id: "chunk-3" }],
          },
          trace: [
            { ordinal: 2, step_type: "draft", role_id: "writer" },
            { ordinal: 0, step_type: "plan", role_id: "planner" },
            { ordinal: 1, step_type: "research", role_id: "researcher" },
          ],
        }),
      ),
    );
    renderView("member");
    const user = await startRun();
    await user.click(screen.getByTestId("multi-result-load"));

    await waitFor(() =>
      expect(screen.getByTestId("multi-result")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("multi-result-status")).toHaveTextContent(
      "terminated",
    );
    expect(screen.getByTestId("multi-result-output")).toHaveTextContent(
      "Persisted final output",
    );
    // Trace ordered by ordinal.
    const entries = screen.getAllByTestId(/^trace-entry-/);
    expect(entries.map((el) => el.getAttribute("data-ordinal"))).toEqual([
      "0",
      "1",
      "2",
    ]);
  });

  it("presents the run as not found on 404 (10.7)", async () => {
    server.use(
      startHandler(),
      http.get(`${BASE}/multi-agent/runs/mrun-1`, () =>
        HttpResponse.json(
          { error: { code: "not_found", message: "Run not found.", details: {} } },
          { status: 404 },
        ),
      ),
    );
    renderView("member");
    const user = await startRun();
    await user.click(screen.getByTestId("multi-result-load"));

    await waitFor(() =>
      expect(screen.getByTestId("multi-result-not-found")).toBeInTheDocument(),
    );
  });

  it("shows a message and refreshes status on a 409 approval conflict (10.8)", async () => {
    server.use(
      startHandler(),
      http.post(`${BASE}/multi-agent/runs/mrun-1/stream`, () =>
        sseResponse([
          renderSseFrame("approval_required", {
            sequence: 0,
            run_id: "mrun-1",
            checkpoint: "Approve?",
          }),
        ]),
      ),
      http.post(`${BASE}/multi-agent/runs/mrun-1/approval`, () =>
        HttpResponse.json(
          {
            error: {
              code: "run-not-awaiting-approval",
              message: "Run is not awaiting approval.",
              details: {},
            },
          },
          { status: 409 },
        ),
      ),
      http.get(`${BASE}/multi-agent/runs/mrun-1`, () =>
        HttpResponse.json({
          run_id: "mrun-1",
          status: "terminated",
          termination_reason: "completed",
          trace: [],
        }),
      ),
    );
    renderView("member");
    const user = await startRun();
    await user.click(screen.getByTestId("multi-stream-open"));
    await waitFor(() =>
      expect(screen.getByTestId("approval-panel")).toBeInTheDocument(),
    );

    await user.click(screen.getByTestId("approval-approve"));

    // Conflict message shown …
    await waitFor(() =>
      expect(screen.getByTestId("approval-conflict")).toBeInTheDocument(),
    );
    // … and the run status is refreshed from the server.
    await waitFor(() =>
      expect(screen.getByTestId("multi-result-status")).toHaveTextContent(
        "terminated",
      ),
    );
  });

  it("omits run controls when the role lacks run_agents (4.2)", () => {
    renderView("viewer");
    expect(screen.getByTestId("multi-agent-view")).toBeInTheDocument();
    expect(screen.queryByTestId("multi-form-card")).toBeNull();
    expect(screen.queryByTestId("multi-start")).toBeNull();
  });
});
