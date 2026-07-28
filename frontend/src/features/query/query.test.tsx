// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { RagQueryView } from "./RagQueryView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
// The Query view resolves citation filenames from GET /documents; a default
// empty-corpus handler keeps unrelated tests green (citations fall back to the
// raw document id). Individual tests override it to exercise filename mapping.
const server = setupServer(
  http.get(`${BASE}/documents`, () => HttpResponse.json([])),
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
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          <RagQueryView />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/**
 * Task 17.1 — RAG query view.
 * _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6_
 */
describe("RagQueryView (MSW)", () => {
  it("submit renders answer + provider (7.1, 7.6)", async () => {
    let sentTopK: number | null | undefined;
    server.use(
      http.post(`${BASE}/query`, async ({ request }) => {
        const body = (await request.json()) as { query: string; top_k?: number | null };
        sentTopK = body.top_k;
        expect(body.query).toBe("what is the policy");
        return HttpResponse.json({
          answer: "The policy is documented in [1].",
          grounded: true,
          provider: "openai",
          citations: [{ document_id: "doc-1", chunk_id: "chunk-9" }],
          flags: [],
        });
      }),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("query-input"), "what is the policy");
    await user.click(screen.getByTestId("query-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("query-answer-card")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("answer-provider")).toHaveTextContent("openai");
    expect(screen.getByTestId("answer-body")).toHaveTextContent(
      "The policy is documented in",
    );
    // top_k was sent.
    expect(typeof sentTopK).toBe("number");
  });

  it("citations render with document_id and chunk_id (7.2)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json({
          answer: "See [1] and [2].",
          grounded: true,
          provider: "anthropic",
          citations: [
            { document_id: "doc-a", chunk_id: "chunk-1" },
            { document_id: "doc-b", chunk_id: "chunk-2" },
          ],
          flags: [],
        }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("query-input"), "hello");
    await user.click(screen.getByTestId("query-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("citation-list")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("citation-doc-1")).toHaveTextContent("doc-a");
    expect(screen.getByTestId("citation-chunk-1")).toHaveTextContent("chunk-1");
    expect(screen.getByTestId("citation-doc-2")).toHaveTextContent("doc-b");
    expect(screen.getByTestId("citation-chunk-2")).toHaveTextContent("chunk-2");
    // Inline [1] marker became a citation link.
    expect(screen.getByTestId("citation-1")).toBeInTheDocument();
  });

  it("resolves citation document ids to human-readable filenames", async () => {
    server.use(
      http.get(`${BASE}/documents`, () =>
        HttpResponse.json([
          {
            document_id: "doc-a",
            filename: "Onboarding Policy.pdf",
            content_type: "application/pdf",
            size_bytes: 1024,
            chunk_count: 3,
            status: "ingested",
            created_at: "2024-01-01T00:00:00Z",
          },
        ]),
      ),
      http.post(`${BASE}/query`, () =>
        HttpResponse.json({
          answer: "See [1].",
          grounded: true,
          provider: "openai",
          citations: [{ document_id: "doc-a", chunk_id: "chunk-1" }],
          flags: [],
        }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("query-input"), "hello");
    await user.click(screen.getByTestId("query-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("citation-doc-1")).toHaveTextContent(
        "Onboarding Policy.pdf",
      ),
    );
    // The raw id remains available for reference via the title attribute.
    expect(screen.getByTestId("citation-doc-1")).toHaveAttribute("title", "doc-a");
  });

  it("renders without crashing when GET /documents returns a non-array body", async () => {
    // A catch-all mock (or an unexpected payload) may return `{}` instead of a
    // list; the view must never try to iterate a non-array (regression guard).
    server.use(
      http.get(`${BASE}/documents`, () => HttpResponse.json({})),
      http.post(`${BASE}/query`, () =>
        HttpResponse.json({
          answer: "Answer [1].",
          grounded: true,
          provider: "openai",
          citations: [{ document_id: "doc-x", chunk_id: "chunk-1" }],
          flags: [],
        }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("query-input"), "hello");
    await user.click(screen.getByTestId("query-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("query-answer-card")).toBeInTheDocument(),
    );
    // Falls back to the raw document id when no filename map is available.
    expect(screen.getByTestId("citation-doc-1")).toHaveTextContent("doc-x");
  });

  it("indicates ungrounded when grounded=false with empty citations (7.3)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json({
          answer: "I could not ground this answer.",
          grounded: false,
          provider: "openai",
          citations: [],
          flags: [],
        }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("query-input"), "unknown");
    await user.click(screen.getByTestId("query-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("ungrounded-indicator")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("grounded-indicator")).toBeNull();
  });

  it("displays guardrail flags (7.4)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json({
          answer: "Answer with flags.",
          grounded: true,
          provider: "openai",
          citations: [],
          flags: ["pii", "toxicity"],
        }),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("query-input"), "flagged");
    await user.click(screen.getByTestId("query-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("answer-flags")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("flag-pii")).toBeInTheDocument();
    expect(screen.getByTestId("flag-toxicity")).toBeInTheDocument();
  });

  it("guardrail_blocked (400) withholds any answer and shows the reason (7.5)", async () => {
    server.use(
      http.post(`${BASE}/query`, () =>
        HttpResponse.json(
          {
            error: {
              code: "guardrail_blocked",
              message: "The request was blocked by a guardrail.",
              details: { reason: "prompt injection detected" },
            },
          },
          { status: 400 },
        ),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.type(screen.getByTestId("query-input"), "malicious");
    await user.click(screen.getByTestId("query-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("query-error")).toBeInTheDocument(),
    );
    // The answer is withheld.
    expect(screen.queryByTestId("query-answer-card")).toBeNull();
    // The block reason from details is surfaced.
    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      "prompt injection detected",
    );
  });

  it("omits the submit control when the role lacks run_agents (4.2)", () => {
    renderView("viewer");
    expect(screen.getByTestId("query-view")).toBeInTheDocument();
    expect(screen.queryByTestId("query-form-card")).toBeNull();
    expect(screen.queryByTestId("query-submit")).toBeNull();
  });
});
