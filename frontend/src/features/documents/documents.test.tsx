// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { DocumentListView } from "./DocumentListView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

/**
 * The `Blob`/`File`/`FormData` globals are aligned with `fetch`'s realm centrally
 * in `src/test/setup.ts` (jsdom's own classes are rejected by undici's multipart
 * parser). A real `File` can therefore be constructed here, and the filename it
 * carries survives the round trip — which the previous Blob-with-a-`name`-property
 * stand-in did not: undici renamed such an entry to "blob".
 */
function makeUploadFile(content: string, name: string, type: string): File {
  return new File([content], name, { type });
}

beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => server.resetHandlers());
afterAll(() => {
  server.close();
});

function renderView(role: Role = "member"): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          <DocumentListView />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function docFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    document_id: "doc-1",
    filename: "policy.pdf",
    content_type: "application/pdf",
    size_bytes: 2048,
    status: "ingested",
    chunk_count: 12,
    created_at: "2024-01-02T03:04:05Z",
    ...overrides,
  };
}

/**
 * Task 18.1 — documents view.
 * _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
 */
describe("DocumentListView (MSW)", () => {
  it("lists document metadata rows (8.3)", async () => {
    server.use(
      http.get(`${BASE}/documents`, () =>
        HttpResponse.json([docFixture()]),
      ),
    );

    renderView("member");
    await waitFor(() =>
      expect(screen.getByTestId("document-row-doc-1")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("document-filename")).toHaveTextContent("policy.pdf");
    expect(screen.getByTestId("document-content-type")).toHaveTextContent(
      "application/pdf",
    );
    expect(screen.getByTestId("document-chunk-count")).toHaveTextContent("12");
    expect(screen.getByTestId("document-status")).toHaveTextContent("ingested");
    expect(screen.getByTestId("document-created-at")).toHaveTextContent(
      "2024-01-02T03:04:05Z",
    );
  });

  it("uploads a file via multipart and shows the result fields (8.1, 8.2)", async () => {
    let uploadCalls = 0;
    let sawMultipart = false;
    server.use(
      http.get(`${BASE}/documents`, () => HttpResponse.json([])),
      http.post(`${BASE}/documents`, async ({ request }) => {
        uploadCalls += 1;
        const contentType = request.headers.get("content-type") ?? "";
        sawMultipart = contentType.includes("multipart/form-data");
        const form = await request.formData();
        const file = form.get("file");
        // The multipart part is a file-like entry carrying the filename.
        expect(file).not.toBeNull();
        expect(typeof file).toBe("object");
        return HttpResponse.json(
          {
            document_id: "doc-99",
            filename: "notes.txt",
            chunk_count: 3,
            status: "ingested",
          },
          { status: 201 },
        );
      }),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("upload-control")).toBeInTheDocument());

    const file = makeUploadFile("hello world", "notes.txt", "text/plain");
    // Drive the upload through the drop-zone with a controlled dataTransfer,
    // bypassing jsdom's file-input machinery.
    fireEvent.drop(screen.getByTestId("drop-zone"), {
      dataTransfer: { files: [file], items: [], types: ["Files"] },
    });

    await waitFor(() => expect(uploadCalls).toBe(1));
    expect(sawMultipart).toBe(true);
    await waitFor(() =>
      expect(screen.getByTestId("upload-result")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("result-document-id")).toHaveTextContent("doc-99");
    expect(screen.getByTestId("result-filename")).toHaveTextContent("notes.txt");
    expect(screen.getByTestId("result-chunk-count")).toHaveTextContent("3");
    expect(screen.getByTestId("result-status")).toHaveTextContent("ingested");
  });

  it("deletes a document and removes its row on 204 (8.4)", async () => {
    let deleteCalls = 0;
    server.use(
      http.get(`${BASE}/documents`, () =>
        HttpResponse.json([docFixture({ document_id: "doc-del", filename: "old.pdf" })]),
      ),
      http.delete(`${BASE}/documents/doc-del`, () => {
        deleteCalls += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderView("member");
    await waitFor(() =>
      expect(screen.getByTestId("document-row-doc-del")).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("document-delete-doc-del"));

    await waitFor(() => expect(deleteCalls).toBe(1));
    await waitFor(() =>
      expect(screen.queryByTestId("document-row-doc-del")).toBeNull(),
    );
  });

  it("surfaces a document error envelope message (8.5)", async () => {
    server.use(
      http.get(`${BASE}/documents`, () => HttpResponse.json([])),
      http.post(`${BASE}/documents`, async ({ request }) => {
        // Consume the request body before responding so undici finalizes it.
        await request.formData();
        return HttpResponse.json(
          {
            error: {
              code: "size_limit_exceeded",
              message: "The uploaded document exceeds the size limit.",
              details: { limit_bytes: 1000000 },
            },
          },
          { status: 413 },
        );
      }),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("upload-control")).toBeInTheDocument());

    const file = makeUploadFile("x".repeat(50), "big.pdf", "application/pdf");
    fireEvent.drop(screen.getByTestId("drop-zone"), {
      dataTransfer: { files: [file], items: [], types: ["Files"] },
    });

    await waitFor(() =>
      expect(screen.getByTestId("upload-error")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("error-banner")).toHaveTextContent(
      "The uploaded document exceeds the size limit.",
    );
  });

  it("omits upload/delete controls when the role lacks ingest_documents (4.3)", async () => {
    server.use(
      http.get(`${BASE}/documents`, () =>
        HttpResponse.json([docFixture({ document_id: "doc-ro" })]),
      ),
    );

    renderView("viewer");
    await waitFor(() =>
      expect(screen.getByTestId("document-row-doc-ro")).toBeInTheDocument(),
    );
    // Upload control and delete affordance are absent from the DOM.
    expect(screen.queryByTestId("upload-control")).toBeNull();
    expect(screen.queryByTestId("document-delete-doc-ro")).toBeNull();
  });
});
