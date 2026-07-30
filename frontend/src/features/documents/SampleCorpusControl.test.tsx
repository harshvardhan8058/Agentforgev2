// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { SampleCorpusControl } from "./SampleCorpusControl";
import { SessionProvider } from "../../auth/SessionProvider";
import { ToastProvider } from "../../providers/ToastProvider";
import { setToken, __resetTokenStoreForTests } from "../../auth/tokenStore";
import { SAMPLE_DOCUMENTS } from "../../lib/examples";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  __resetTokenStoreForTests();
  localStorage.clear();
});
afterAll(() => server.close());

function b64url(obj: unknown): string {
  return btoa(JSON.stringify(obj))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function renderControl(): void {
  setToken(
    `${b64url({ alg: "HS256" })}.${b64url({
      sub: "u1",
      org_id: "org-1",
      role: "owner",
      exp: 9_999_999_999,
    })}.sig`,
  );
  render(
    <ToastProvider>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <SessionProvider>
          <SampleCorpusControl />
        </SessionProvider>
      </QueryClientProvider>
    </ToastProvider>,
  );
}

/**
 * The one-click sample corpus.
 *
 * Its whole justification is that retrieval is unusable against an empty
 * corpus, so the behaviour that matters is that it really ingests every sample
 * through the real `POST /documents` multipart endpoint — not a seeding
 * backdoor. If it silently posted only the first document, or posted JSON
 * instead of multipart, the demo would still look like it worked here while
 * failing against the live API.
 */
describe("SampleCorpusControl", () => {
  it("lists every sample document before anything is loaded", () => {
    renderControl();

    for (const sample of SAMPLE_DOCUMENTS) {
      expect(screen.getByText(sample.filename)).toBeInTheDocument();
    }
  });

  it("ingests every sample document through POST /documents", async () => {
    const uploaded: string[] = [];
    server.use(
      // Assertions stay outside the handler: a failing expect() inside it is
      // caught by MSW and turned into a 500, which hides the real cause.
      http.post(`${BASE}/documents`, async ({ request }) => {
        const form = await request.formData();
        // The explicit `filename` part, not the File's own name: under jsdom the
        // multipart filename is rewritten to "blob", and `filename` is the field
        // the API names the document from in any case.
        uploaded.push(String(form.get("filename")));
        return HttpResponse.json(
          {
            document_id: `doc-${uploaded.length}`,
            filename: String(form.get("filename")),
            chunk_count: 3,
            status: "ingested",
          },
          { status: 201 },
        );
      }),
    );

    renderControl();
    await userEvent.click(screen.getByTestId("load-sample-corpus"));

    await waitFor(() =>
      expect(screen.getByTestId("sample-corpus-loaded")).toBeInTheDocument(),
    );
    // Every sample, in catalogue order, one request each.
    expect(uploaded).toEqual(SAMPLE_DOCUMENTS.map((s) => s.filename));
  });

  it("sends the document's real content as the file body", async () => {
    const bodies: string[] = [];
    server.use(
      http.post(`${BASE}/documents`, async ({ request }) => {
        const form = await request.formData();
        bodies.push(await (form.get("file") as File).text());
        return HttpResponse.json(
          { document_id: "d", filename: "f", chunk_count: 1, status: "ingested" },
          { status: 201 },
        );
      }),
    );

    renderControl();
    await userEvent.click(screen.getByTestId("load-sample-corpus"));

    await waitFor(() =>
      expect(bodies.length).toBe(SAMPLE_DOCUMENTS.length),
    );
    expect(bodies[0]).toBe(SAMPLE_DOCUMENTS[0].content);
  });

  it("surfaces a failure instead of reporting success", async () => {
    server.use(
      http.post(`${BASE}/documents`, () =>
        HttpResponse.json(
          {
            error: {
              code: "unsupported_media_type",
              message: "Unsupported file type.",
              details: {},
            },
          },
          { status: 415 },
        ),
      ),
    );

    renderControl();
    await userEvent.click(screen.getByTestId("load-sample-corpus"));

    await waitFor(() =>
      expect(screen.getByTestId("sample-corpus-error")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("sample-corpus-loaded")).not.toBeInTheDocument();
  });

  it("stops at the first failure rather than continuing through the corpus", async () => {
    let calls = 0;
    server.use(
      http.post(`${BASE}/documents`, () => {
        calls += 1;
        return HttpResponse.json(
          { error: { code: "internal_error", message: "Boom.", details: {} } },
          { status: 500 },
        );
      }),
    );

    renderControl();
    await userEvent.click(screen.getByTestId("load-sample-corpus"));

    await waitFor(() =>
      expect(screen.getByTestId("sample-corpus-error")).toBeInTheDocument(),
    );
    // A partially-ingested corpus with a success message would be misleading.
    expect(calls).toBe(1);
  });
});
