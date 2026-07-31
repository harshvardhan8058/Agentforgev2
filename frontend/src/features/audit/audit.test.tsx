// @vitest-environment jsdom
import { describe, it, expect, beforeAll, beforeEach, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";
import { axe } from "vitest-axe";
import { toHaveNoViolations } from "vitest-axe/dist/matchers.js";

// vitest-axe ships its type augmentation for an older Vitest `Vi` namespace; declare the
// matcher against Vitest's `Assertion` interface directly.
declare module "vitest" {
  // Must match Vitest's own `Assertion<T = any>` type-parameter signature.
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}

import { AuditLogView } from "./AuditLogView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

expect.extend({ toHaveNoViolations });

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

// jsdom computes no layout, so contrast is unverifiable here (the Playwright axe lane
// covers it in a real browser).
const AXE_OPTIONS = { rules: { "color-contrast": { enabled: false } } };

function renderView(role: Role = "admin"): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <SessionContext.Provider value={makeSession(role)}>
        <AuditLogView />
      </SessionContext.Provider>
    </QueryClientProvider>,
  );
}

function event(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    action: "member.added",
    actor_kind: "user",
    actor_id: "22222222-2222-4222-8222-222222222222",
    actor_email: "owner@example.com",
    target_type: "member",
    target_id: "33333333-3333-4333-8333-333333333333",
    metadata: { email: "new@example.com", role: "member" },
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

/** Requests the view made, so filter wiring can be asserted on the query string. */
let requests: URL[] = [];

beforeEach(() => {
  requests = [];
  server.use(
    http.get(`${BASE}/audit-events`, ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json([event()]);
    }),
  );
});

/**
 * The audit log: the answer to "who changed this, and when".
 * Gated on `read_audit_log`, which is granted from `admin` upwards.
 */
describe("AuditLogView (MSW)", () => {
  it("renders the trail newest-first with actor, action and details", async () => {
    server.use(
      http.get(`${BASE}/audit-events`, () =>
        HttpResponse.json([
          event({ id: "e2", action: "api_key.revoked", metadata: { key_prefix: "af_live_ab" } }),
          event({ id: "e1" }),
        ]),
      ),
    );

    renderView("admin");

    await waitFor(() => expect(screen.getByTestId("audit-table")).toBeInTheDocument());
    const rows = screen.getAllByTestId(/^audit-row-/);
    // Order is the server's; the client does not re-sort what it was given.
    expect(rows[0]).toHaveAttribute("data-testid", "audit-row-e2");
    expect(rows[0]).toHaveTextContent("API key revoked");
    expect(rows[0]).toHaveTextContent("af_live_ab");
    expect(rows[1]).toHaveTextContent("Member added");
    expect(rows[1]).toHaveTextContent("owner@example.com");
    expect(rows[1]).toHaveTextContent("new@example.com");
  });

  it("sends the selected action as a query filter", async () => {
    renderView("admin");
    await waitFor(() => expect(requests.length).toBe(1));
    expect(requests[0].searchParams.get("action")).toBeNull();
    expect(requests[0].searchParams.get("limit")).toBe("50");

    const user = userEvent.setup();
    await user.click(screen.getByTestId("audit-action-trigger"));
    await user.click(screen.getByTestId("audit-action-member.removed"));

    await waitFor(() => expect(requests.length).toBe(2));
    expect(requests[1].searchParams.getAll("action")).toEqual(["member.removed"]);
  });

  it("sends the selected page size", async () => {
    renderView("admin");
    await waitFor(() => expect(requests.length).toBe(1));

    const user = userEvent.setup();
    await user.click(screen.getByTestId("audit-limit-trigger"));
    await user.click(screen.getByTestId("audit-limit-200"));

    await waitFor(() =>
      expect(requests[requests.length - 1].searchParams.get("limit")).toBe("200"),
    );
  });

  it("names an API-key actor and a deleted user honestly", async () => {
    server.use(
      http.get(`${BASE}/audit-events`, () =>
        HttpResponse.json([
          event({
            id: "e-key",
            actor_kind: "api_key",
            actor_email: null,
            actor_id: "abcdef12-3456-4111-8111-111111111111",
          }),
          event({ id: "e-gone", actor_kind: "user", actor_email: null }),
        ]),
      ),
    );

    renderView("owner");

    await waitFor(() => expect(screen.getByTestId("audit-table")).toBeInTheDocument());
    // A key has no display name, so it is identified by its id...
    expect(screen.getByTestId("audit-row-e-key")).toHaveTextContent("API key abcdef12");
    // ...and a user who has since been deleted is said to be, not hidden.
    expect(screen.getByTestId("audit-row-e-gone")).toHaveTextContent("Deleted user");
  });

  it("shows an empty state that distinguishes 'nothing yet' from 'nothing matching'", async () => {
    server.use(http.get(`${BASE}/audit-events`, () => HttpResponse.json([])));

    renderView("admin");

    await waitFor(() =>
      expect(screen.getByText("No administrative activity yet")).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("audit-action-trigger"));
    await user.click(screen.getByTestId("audit-action-team.deleted"));

    await waitFor(() =>
      expect(screen.getByText("No matching entries")).toBeInTheDocument(),
    );
  });

  it("surfaces a failure with a retry", async () => {
    server.use(
      http.get(`${BASE}/audit-events`, () =>
        HttpResponse.json(
          { error: { code: "internal_error", message: "boom", details: {} } },
          { status: 500 },
        ),
      ),
    );

    renderView("admin");

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toHaveTextContent("boom"),
    );
    expect(screen.queryByTestId("audit-table")).toBeNull();
  });

  it("omits the trail entirely for a role without read_audit_log", () => {
    // Rendered without any request: a member must not even ask for it.
    renderView("member");

    expect(screen.getByTestId("audit-view")).toBeInTheDocument();
    expect(screen.getByText("Audit log unavailable")).toBeInTheDocument();
    expect(screen.queryByTestId("audit-filters")).toBeNull();
    expect(screen.queryByTestId("audit-table")).toBeNull();
    expect(requests).toEqual([]);
  });

  it("has no axe violations with a populated trail", async () => {
    const { container } = renderView("admin");
    await waitFor(() => expect(screen.getByTestId("audit-table")).toBeInTheDocument());

    const results = await axe(container, AXE_OPTIONS);
    expect(results).toHaveNoViolations();
  });
});
