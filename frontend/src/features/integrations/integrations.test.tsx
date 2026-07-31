// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { IntegrationsView } from "./IntegrationsView";
import { SessionContext } from "../../auth/useSession";
import { ToastProvider } from "../../providers/ToastProvider";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";

/** A usage report with only the fields this view reads populated. */
function usageReport(byProvider: { key: string; total_tokens: number }[]) {
  return {
    org_id: "org-1",
    start: null,
    end: null,
    total_tokens: byProvider.reduce((n, p) => n + p.total_tokens, 0),
    total_cost: "0",
    by_provider: byProvider.map((p) => ({ ...p, total_cost: "0" })),
    by_model: [],
    by_user: [],
  };
}

const server = setupServer(
  // Sensible defaults; individual tests override what they assert on.
  http.get(`${BASE}/integrations/status`, () => HttpResponse.json({ integrations: [] })),
  http.get(`${BASE}/analytics/usage`, () => HttpResponse.json(usageReport([]))),
  // The connection-settings panel always lists stored config.
  http.get(`${BASE}/integrations/connections`, () => HttpResponse.json([])),
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
          <IntegrationsView />
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/**
 * `IntegrationsView` — surfaces `GET /integrations/status` (which previously had
 * no frontend route at all) plus the language-model provider actually serving
 * traffic, derived from the usage report's `by_provider` breakdown.
 */
describe("IntegrationsView (MSW)", () => {
  it("lists each connector with its enabled state", async () => {
    server.use(
      http.get(`${BASE}/integrations/status`, () =>
        HttpResponse.json({
          integrations: [
            { name: "slack", enabled: true },
            { name: "gmail", enabled: false },
            { name: "google_drive", enabled: false },
            { name: "github", enabled: false },
          ],
        }),
      ),
    );

    renderView();
    await waitFor(() => expect(screen.getByTestId("connectors-list")).toBeInTheDocument());

    // Friendly labels, not raw backend keys.
    expect(screen.getByTestId("connector-name-google_drive").textContent).toBe("Google Drive");

    // Enabled state is exposed both visually and as a stable data attribute.
    expect(screen.getByTestId("connector-slack")).toHaveAttribute("data-enabled", "true");
    expect(screen.getByTestId("connector-gmail")).toHaveAttribute("data-enabled", "false");
    expect(screen.getByTestId("connector-state-slack").textContent).toContain("Enabled");
    expect(screen.getByTestId("connector-state-gmail").textContent).toContain("Not configured");
  });

  it("renders an unknown connector name rather than hiding it", async () => {
    server.use(
      http.get(`${BASE}/integrations/status`, () =>
        HttpResponse.json({ integrations: [{ name: "notion_beta", enabled: false }] }),
      ),
    );

    renderView();
    await waitFor(() =>
      expect(screen.getByTestId("connector-name-notion_beta")).toBeInTheDocument(),
    );
    // Title-cased fallback label so a new backend connector is never invisible.
    expect(screen.getByTestId("connector-name-notion_beta").textContent).toBe("Notion Beta");
  });

  it("renders an empty state when the deployment reports no connectors", async () => {
    renderView();
    await waitFor(() => expect(screen.getByTestId("connectors-empty")).toBeInTheDocument());
  });

  it("explains keyless mode when the fallback provider served traffic", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(usageReport([{ key: "fallback", total_tokens: 1200 }])),
      ),
    );

    renderView();
    await waitFor(() =>
      expect(screen.getByTestId("model-provider-fallback")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("model-provider-fallback").textContent).toContain("GROQ_API_KEY");
    expect(screen.queryByTestId("model-provider-unknown")).toBeNull();
  });

  it("shows the real provider and no fallback notice once one is configured", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(usageReport([{ key: "groq", total_tokens: 500 }])),
      ),
    );

    renderView();
    await waitFor(() => expect(screen.getByTestId("model-provider-groq")).toBeInTheDocument());
    expect(screen.queryByTestId("model-provider-fallback")).toBeNull();
  });

  it("ignores providers with no recorded tokens", async () => {
    server.use(
      http.get(`${BASE}/analytics/usage`, () =>
        HttpResponse.json(usageReport([{ key: "fallback", total_tokens: 0 }])),
      ),
    );

    renderView();
    // A zero-token entry is not evidence the provider served anything.
    await waitFor(() => expect(screen.getByTestId("model-provider-unknown")).toBeInTheDocument());
    expect(screen.queryByTestId("model-provider-fallback")).toBeNull();
  });

  it("stays usable when the usage endpoint returns a non-array payload", async () => {
    // The API contract says by_provider is an array; a malformed/mocked body
    // must not crash the page (mirrors the e2e catch-all returning {}).
    server.use(http.get(`${BASE}/analytics/usage`, () => HttpResponse.json({})));

    renderView();
    await waitFor(() => expect(screen.getByTestId("model-provider-unknown")).toBeInTheDocument());
    expect(screen.getByTestId("integrations-view")).toBeInTheDocument();
  });

  // ---- connection settings (`/integrations/connections`) ----
  //
  // The Integration_Connection store, its Postgres implementation and migration 0011 all
  // shipped with no HTTP surface, so per-org connector config was unreachable from
  // anywhere. These cover the panel that closes that, including the two things it must
  // not do: imply that saving config enables a connector, and offer write controls to a
  // role the server would refuse.

  it("lists stored connector settings for any role that can read", async () => {
    server.use(
      http.get(`${BASE}/integrations/connections`, () =>
        HttpResponse.json([
          {
            connection_id: "c1",
            integration: "slack",
            config: { default_channel: "#ops", notify: true },
            created_at: "2026-07-01T00:00:00Z",
          },
        ]),
      ),
    );

    renderView("viewer");

    await waitFor(() =>
      expect(screen.getByTestId("connections-config-list")).toBeInTheDocument(),
    );
    const row = screen.getByTestId("connection-c1");
    expect(row).toHaveTextContent("slack");
    expect(row).toHaveTextContent("default_channel");
    expect(row).toHaveTextContent("#ops");
    // A viewer holds no manage_integrations, so every write control is ABSENT.
    expect(screen.queryByTestId("add-connection-form")).toBeNull();
    expect(screen.queryByTestId("edit-connection-c1")).toBeNull();
    expect(screen.queryByTestId("remove-connection-c1")).toBeNull();
  });

  it("creates a connector configuration from key/value rows (admin)", async () => {
    let posted: { integration: string; config: Record<string, unknown> } | null = null;
    server.use(
      http.get(`${BASE}/integrations/status`, () =>
        HttpResponse.json({
          integrations: [
            { name: "slack", enabled: false },
            { name: "github", enabled: false },
          ],
        }),
      ),
      http.post(`${BASE}/integrations/connections`, async ({ request }) => {
        posted = (await request.json()) as {
          integration: string;
          config: Record<string, unknown>;
        };
        return HttpResponse.json(
          {
            connection_id: "c2",
            integration: posted.integration,
            config: posted.config,
            created_at: "2026-07-31T00:00:00Z",
          },
          { status: 201 },
        );
      }),
    );

    renderView("admin");
    await waitFor(() =>
      expect(screen.getByTestId("add-connection-form")).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    // Pick the second connector to prove the selection is honoured, not defaulted.
    await user.click(screen.getByTestId("new-connection-integration"));
    await user.click(screen.getByTestId("new-connection-integration-github"));
    await user.type(screen.getByTestId("new-connection-key-0"), "repo");
    await user.type(screen.getByTestId("new-connection-value-0"), "acme/platform");
    await user.click(screen.getByTestId("create-connection"));

    await waitFor(() =>
      expect(posted).toEqual({
        integration: "github",
        config: { repo: "acme/platform" },
      }),
    );
  });

  it("surfaces the server's refusal of a credential-shaped setting verbatim", async () => {
    server.use(
      http.get(`${BASE}/integrations/status`, () =>
        HttpResponse.json({ integrations: [{ name: "slack", enabled: false }] }),
      ),
      http.post(`${BASE}/integrations/connections`, () =>
        HttpResponse.json(
          {
            error: {
              code: "invalid_config",
              message:
                "config key 'bot_token' names a credential; integration connections store NON-SECRET configuration only.",
              details: { field: "config" },
            },
          },
          { status: 400 },
        ),
      ),
    );

    renderView("admin");
    await waitFor(() =>
      expect(screen.getByTestId("add-connection-form")).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    await user.type(screen.getByTestId("new-connection-key-0"), "bot_token");
    await user.type(screen.getByTestId("new-connection-value-0"), "placeholder");
    await user.click(screen.getByTestId("create-connection"));

    // The client does not re-implement the rule; it presents the server's reason.
    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toHaveTextContent(
        "names a credential",
      ),
    );
  });

  it("replaces a stored configuration through PATCH", async () => {
    let patched: Record<string, unknown> | null = null;
    server.use(
      http.get(`${BASE}/integrations/connections`, () =>
        HttpResponse.json([
          {
            connection_id: "c1",
            integration: "slack",
            config: { default_channel: "#ops" },
            created_at: "2026-07-01T00:00:00Z",
          },
        ]),
      ),
      http.patch(`${BASE}/integrations/connections/c1`, async ({ request }) => {
        const body = (await request.json()) as { config: Record<string, unknown> };
        patched = body.config;
        return HttpResponse.json({
          connection_id: "c1",
          integration: "slack",
          config: body.config,
          created_at: "2026-07-01T00:00:00Z",
        });
      }),
    );

    renderView("owner");
    await waitFor(() => expect(screen.getByTestId("edit-connection-c1")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId("edit-connection-c1"));
    // The editor is pre-filled from the stored config; change the value in place.
    const valueInput = screen.getByTestId("edit-c1-value-0");
    await user.clear(valueInput);
    await user.type(valueInput, "#platform");
    await user.click(screen.getByTestId("save-connection-c1"));

    await waitFor(() => expect(patched).toEqual({ default_channel: "#platform" }));
  });

  it("preserves the type of a value the user did not edit", async () => {
    // Regression: rendering values with String() and submitting strings rewrote an
    // untouched `notify: true` as "true" - a silent type change to a record another
    // system is meant to read, and "false" is truthy to every such reader.
    let patched: Record<string, unknown> | null = null;
    server.use(
      http.get(`${BASE}/integrations/connections`, () =>
        HttpResponse.json([
          {
            connection_id: "c1",
            integration: "slack",
            config: { default_channel: "#ops", notify: true, max_results: 5 },
            created_at: "2026-07-01T00:00:00Z",
          },
        ]),
      ),
      http.patch(`${BASE}/integrations/connections/c1`, async ({ request }) => {
        const body = (await request.json()) as { config: Record<string, unknown> };
        patched = body.config;
        return HttpResponse.json({
          connection_id: "c1",
          integration: "slack",
          config: body.config,
          created_at: "2026-07-01T00:00:00Z",
        });
      }),
    );

    renderView("admin");
    await waitFor(() => expect(screen.getByTestId("edit-connection-c1")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId("edit-connection-c1"));
    // Edit ONLY the first row's value.
    const channel = screen.getByTestId("edit-c1-value-0");
    await user.clear(channel);
    await user.type(channel, "#platform");
    await user.click(screen.getByTestId("save-connection-c1"));

    await waitFor(() =>
      expect(patched).toEqual({
        default_channel: "#platform",
        notify: true,
        max_results: 5,
      }),
    );
  });

  it("removes a stored configuration after confirmation", async () => {
    let deleted = 0;
    server.use(
      http.get(`${BASE}/integrations/connections`, () =>
        HttpResponse.json(
          deleted === 0
            ? [
                {
                  connection_id: "c1",
                  integration: "slack",
                  config: {},
                  created_at: "2026-07-01T00:00:00Z",
                },
              ]
            : [],
        ),
      ),
      http.delete(`${BASE}/integrations/connections/c1`, () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderView("admin");
    await waitFor(() =>
      expect(screen.getByTestId("remove-connection-c1")).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("remove-connection-c1"));
    await user.click(screen.getByTestId("confirm-remove-connection-c1"));

    await waitFor(() => expect(deleted).toBe(1));
    await waitFor(() =>
      expect(screen.getByTestId("connections-config-empty")).toBeInTheDocument(),
    );
  });
});
