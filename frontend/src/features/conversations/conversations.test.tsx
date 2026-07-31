// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { ConversationView } from "./ConversationView";
import { ConversationProvider } from "./ConversationContext";
import { MultiAgentRunView } from "../multiAgent/MultiAgentRunView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import { __resetTokenStoreForTests } from "../../auth/tokenStore";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
// The start surface now also lists existing threads, so every render of it calls
// `GET /conversations`. Registered as a default handler (which `resetHandlers` restores)
// so the strict `onUnhandledRequest: "error"` guard stays satisfied without every test
// having to opt in; the listing tests below override it.
const server = setupServer(
  http.get(`${BASE}/conversations`, () => HttpResponse.json([])),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  __resetTokenStoreForTests();
});
afterAll(() => server.close());

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

/** Render the conversation routes under a MemoryRouter at `initialPath`. */
function renderConversations(
  initialPath: string,
  role: Role = "member",
): void {
  render(
    <QueryClientProvider client={makeClient()}>
      <ToastProvider>
        <ConversationProvider>
          <SessionContext.Provider value={makeSession(role)}>
            <MemoryRouter initialEntries={[initialPath]}>
              <Routes>
                <Route path="/conversations" element={<ConversationView />} />
                <Route path="/conversations/:id" element={<ConversationView />} />
              </Routes>
            </MemoryRouter>
          </SessionContext.Provider>
        </ConversationProvider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/**
 * Task 25.1 — conversation context (MSW).
 * _Requirements: 15.1, 15.2, 15.3, 15.4_
 */
describe("Conversation context (MSW)", () => {
  it("creates a conversation and retains its id (15.1)", async () => {
    server.use(
      http.post(`${BASE}/conversations`, () =>
        HttpResponse.json({ conversation_id: "new-conv-1" }, { status: 201 }),
      ),
      http.get(`${BASE}/conversations/new-conv-1`, () =>
        HttpResponse.json({ conversation_id: "new-conv-1", messages: [] }),
      ),
    );
    renderConversations("/conversations");
    const user = userEvent.setup();

    await user.click(screen.getByTestId("conversation-start"));

    // Navigated to the new conversation and its id is shown/retained.
    await waitFor(() =>
      expect(screen.getByTestId("conversation-id")).toHaveTextContent(
        "new-conv-1",
      ),
    );
  });

  it("threads the retained conversation_id into a run request (15.2)", async () => {
    let capturedBody: Record<string, unknown> | null = null;
    server.use(
      http.post(`${BASE}/multi-agent/runs`, async ({ request }) => {
        capturedBody = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(
          {
            run_id: "mrun-9",
            conversation_id: "seed-conv",
            status: "running",
            flags: [],
          },
          { status: 201 },
        );
      }),
    );

    render(
      <QueryClientProvider client={makeClient()}>
        <ToastProvider>
          <ConversationProvider initialConversationId="seed-conv">
            <SessionContext.Provider value={makeSession("member")}>
              <MultiAgentRunView />
            </SessionContext.Provider>
          </ConversationProvider>
        </ToastProvider>
      </QueryClientProvider>,
    );

    const user = userEvent.setup();
    await user.type(screen.getByTestId("multi-task"), "continue thread");
    await user.click(screen.getByTestId("multi-start"));

    await waitFor(() =>
      expect(screen.getByTestId("multi-run-summary")).toBeInTheDocument(),
    );
    expect(capturedBody).not.toBeNull();
    expect(capturedBody).toMatchObject({ conversation_id: "seed-conv" });
  });

  it("renders conversation history ordered by position (15.3)", async () => {
    server.use(
      http.get(`${BASE}/conversations/conv-hist`, () =>
        HttpResponse.json({
          conversation_id: "conv-hist",
          // Deliberately out of order — the view must sort by position.
          messages: [
            { role: "assistant", content: "second", position: 1 },
            { role: "user", content: "first", position: 0 },
            { role: "assistant", content: "third", position: 2 },
          ],
        }),
      ),
    );
    renderConversations("/conversations/conv-hist");

    await waitFor(() =>
      expect(screen.getByTestId("conversation-messages")).toBeInTheDocument(),
    );
    const items = within(
      screen.getByTestId("conversation-messages"),
    ).getAllByRole("listitem");
    expect(items.map((el) => el.getAttribute("data-position"))).toEqual([
      "0",
      "1",
      "2",
    ]);
    // First rendered message is the position-0 one.
    expect(items[0]).toHaveTextContent("first");
  });

  it("presents the conversation as not found on 404 (15.4)", async () => {
    server.use(
      http.get(`${BASE}/conversations/missing`, () =>
        HttpResponse.json(
          {
            error: { code: "not_found", message: "Conversation not found.", details: {} },
          },
          { status: 404 },
        ),
      ),
    );
    renderConversations("/conversations/missing");

    await waitFor(() =>
      expect(screen.getByTestId("conversation-not-found")).toBeInTheDocument(),
    );
  });
});



/**
 * The conversation listing.
 *
 * Creating a thread returned its id once and nothing could enumerate threads
 * afterwards, so the page titled "Conversations" could not show a single one and a
 * thread became unreachable as soon as its id left the screen.
 */
describe("RecentConversations", () => {
  it("lists existing threads by their first message, not their id", async () => {
    server.use(
      http.get(`${BASE}/conversations`, () =>
        HttpResponse.json([
          {
            conversation_id: "c-1",
            created_at: new Date().toISOString(),
            message_count: 2,
            preview: "What does onboarding provide?",
          },
        ]),
      ),
    );

    renderConversations("/conversations");

    await waitFor(() =>
      expect(screen.getByTestId("conversations-list")).toBeInTheDocument(),
    );
    expect(screen.getByText("What does onboarding provide?")).toBeInTheDocument();
    expect(screen.getByText("2 messages")).toBeInTheDocument();
  });

  it("links each row to that conversation", async () => {
    server.use(
      http.get(`${BASE}/conversations`, () =>
        HttpResponse.json([
          {
            conversation_id: "c-42",
            created_at: new Date().toISOString(),
            message_count: 1,
            preview: "Hello",
          },
        ]),
      ),
    );

    renderConversations("/conversations");

    const row = await screen.findByTestId("conversation-row-c-42");
    expect(row).toHaveAttribute("href", "/conversations/c-42");
  });

  it("labels a thread with no messages rather than showing a blank row", async () => {
    server.use(
      http.get(`${BASE}/conversations`, () =>
        HttpResponse.json([
          {
            conversation_id: "c-empty",
            created_at: new Date().toISOString(),
            message_count: 0,
            preview: null,
          },
        ]),
      ),
    );

    renderConversations("/conversations");

    expect(await screen.findByText("Empty conversation")).toBeInTheDocument();
    expect(screen.getByText("0 messages")).toBeInTheDocument();
  });

  it("shows an empty state when the org has no conversations", async () => {
    renderConversations("/conversations");

    await waitFor(() =>
      expect(screen.getByTestId("conversations-empty")).toBeInTheDocument(),
    );
  });

  it("surfaces a listing failure without breaking the start control", async () => {
    // The two are independent: being unable to list must not prevent creating.
    server.use(
      http.get(`${BASE}/conversations`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "Boom.", details: {} } },
          { status: 500 },
        ),
      ),
    );

    renderConversations("/conversations");

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("conversation-start")).toBeInTheDocument();
  });
});
