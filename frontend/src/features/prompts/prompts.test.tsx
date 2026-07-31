// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import type { Role } from "../../auth/token";

// `PromptStudio` used to be mocked here because it wrapped Monaco, which is
// fetched from a CDN and must never be loaded under Vitest. It is now a plain
// textarea plus a pure diff, so the real component renders in these tests —
// the editor was previously stubbed out of every assertion.
import { PromptRegistryView } from "./PromptRegistryView";

const BASE = "http://localhost:8000";
const server = setupServer();

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
          <PromptRegistryView />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

function versionFixture(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "pv-1",
    name: "greeting",
    version: 2,
    body: "Hello {{name}} about {{topic}}",
    variables: ["name", "topic"],
    created_at: "2024-03-04T05:06:07Z",
    ...overrides,
  };
}

/**
 * Task 23.2 — prompt registry.
 * _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.7_
 */
describe("PromptRegistryView (MSW)", () => {
  it("lists template names (12.1)", async () => {
    server.use(http.get(`${BASE}/prompts`, () => HttpResponse.json(["greeting", "summary"])));

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("template-greeting")).toBeInTheDocument());
    expect(screen.getByTestId("template-summary")).toBeInTheDocument();
  });

  it("shows ascending version numbers and the selected version detail (12.2, 12.3)", async () => {
    server.use(
      http.get(`${BASE}/prompts`, () => HttpResponse.json(["greeting"])),
      http.get(`${BASE}/prompts/greeting/versions`, () => HttpResponse.json([1, 2])),
      http.get(`${BASE}/prompts/greeting`, ({ request }) => {
        const version = Number(new URL(request.url).searchParams.get("version"));
        return HttpResponse.json(versionFixture({ version }));
      }),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("template-greeting"));

    // Versions listed ascending (v1 then v2).
    await waitFor(() => expect(screen.getByTestId("version-list")).toBeInTheDocument());
    const versionButtons = screen.getAllByTestId(/^version-\d+$/);
    expect(versionButtons.map((b) => b.textContent)).toEqual(["v1", "v2"]);

    // Latest version detail is shown (body/variables/created-at).
    await waitFor(() => expect(screen.getByTestId("version-detail-card")).toBeInTheDocument());
    expect(screen.getByTestId("version-created-at").textContent).toBe("2024-03-04T05:06:07Z");
    expect(screen.getByTestId("version-variable-name")).toBeInTheDocument();
    expect(screen.getByTestId("version-variable-topic")).toBeInTheDocument();
  });

  it("creates a version (gated) and shows the returned number (12.4)", async () => {
    let created = 0;
    server.use(
      http.get(`${BASE}/prompts`, () => HttpResponse.json([])),
      http.post(`${BASE}/prompts`, async ({ request }) => {
        created += 1;
        const body = (await request.json()) as { name: string };
        return HttpResponse.json(versionFixture({ name: body.name, version: 3 }), {
          status: 201,
        });
      }),
    );

    renderView("member");
    await waitFor(() => expect(screen.getByTestId("create-version-form")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByTestId("prompt-name"), "greeting");
    await user.type(screen.getByTestId("prompt-variables"), "name");
    await user.click(screen.getByTestId("create-version-submit"));

    await waitFor(() => expect(created).toBe(1));
    await waitFor(() =>
      expect(screen.getByTestId("create-version-result").textContent).toContain("3"),
    );
  });

  it("omits the create-version control without ingest_documents (4.3)", async () => {
    server.use(http.get(`${BASE}/prompts`, () => HttpResponse.json([])));
    renderView("viewer");
    await waitFor(() => expect(screen.getByTestId("template-list-card")).toBeInTheDocument());
    expect(screen.queryByTestId("create-version-card")).toBeNull();
  });

  it("blocks render until all variables are supplied, then renders (12.5, 12.6)", async () => {
    let renderCalls = 0;
    server.use(
      http.get(`${BASE}/prompts`, () => HttpResponse.json(["greeting"])),
      http.get(`${BASE}/prompts/greeting/versions`, () => HttpResponse.json([2])),
      http.get(`${BASE}/prompts/greeting`, () => HttpResponse.json(versionFixture())),
      http.post(`${BASE}/prompts/greeting/render`, () => {
        renderCalls += 1;
        return HttpResponse.json({ name: "greeting", version: 2, rendered: "Hello Ada about AI" });
      }),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("template-greeting"));
    await waitFor(() => expect(screen.getByTestId("render-form")).toBeInTheDocument());

    // Submit is blocked while variables are missing (no request issued).
    expect((screen.getByTestId("render-submit") as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByTestId("render-missing-prompt").textContent).toContain("name");

    await user.type(screen.getByTestId("render-var-name"), "Ada");
    await user.type(screen.getByTestId("render-var-topic"), "AI");
    expect((screen.getByTestId("render-submit") as HTMLButtonElement).disabled).toBe(false);

    await user.click(screen.getByTestId("render-submit"));
    await waitFor(() => expect(renderCalls).toBe(1));
    await waitFor(() =>
      expect(screen.getByTestId("render-output").textContent).toBe("Hello Ada about AI"),
    );
  });

  it("surfaces missing variable names on 400 missing_variable (12.7)", async () => {
    server.use(
      http.get(`${BASE}/prompts`, () => HttpResponse.json(["greeting"])),
      http.get(`${BASE}/prompts/greeting/versions`, () => HttpResponse.json([2])),
      // Version declares only `name` so the form can submit, but the server
      // reports a missing variable in the envelope details.
      http.get(`${BASE}/prompts/greeting`, () =>
        HttpResponse.json(versionFixture({ variables: ["name"] })),
      ),
      http.post(`${BASE}/prompts/greeting/render`, () =>
        HttpResponse.json(
          {
            error: {
              code: "missing_variable",
              message: "A required variable was not supplied.",
              details: { missing: ["topic"] },
            },
          },
          { status: 400 },
        ),
      ),
    );

    renderView("member");
    const user = userEvent.setup();
    await user.click(await screen.findByTestId("template-greeting"));
    await waitFor(() => expect(screen.getByTestId("render-form")).toBeInTheDocument());

    await user.type(screen.getByTestId("render-var-name"), "Ada");
    await user.click(screen.getByTestId("render-submit"));

    await waitFor(() => expect(screen.getByTestId("render-server-missing")).toBeInTheDocument());
    expect(screen.getByTestId("render-server-missing").textContent).toContain("topic");
  });
});
