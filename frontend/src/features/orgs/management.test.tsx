// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { MembersView } from "./MembersView";
import { ApiKeysView } from "./ApiKeysView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import type { Role } from "../../auth/token";
import { type ReactNode } from "react";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderView(ui: ReactNode, role: Role): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
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

/**
 * Task 16.1 — RBAC gating of org member/team + API-key management.
 * _Requirements: 4.4, 4.5_
 */
describe("org management gating (MSW)", () => {
  it("manage_members present → member/team controls in DOM and wired to /orgs/* (4.4)", async () => {
    let addMemberCalls = 0;
    server.use(
      http.post(`${BASE}/orgs/org-1/members`, async ({ request }) => {
        addMemberCalls += 1;
        const body = (await request.json()) as { email: string; role: Role };
        expect(body.email).toBe("teammate@example.com");
        return HttpResponse.json(
          { org_id: "org-1", role: body.role, user_id: "u2" },
          { status: 201 },
        );
      }),
    );

    renderView(<MembersView />, "owner");
    // Controls present.
    expect(screen.getByTestId("add-member-card")).toBeInTheDocument();
    expect(screen.getByTestId("create-team-card")).toBeInTheDocument();
    expect(screen.getByTestId("add-member-submit")).toBeInTheDocument();

    // Wired to POST /orgs/{org_id}/members.
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "teammate@example.com");
    await user.click(screen.getByTestId("add-member-submit"));
    await waitFor(() => expect(addMemberCalls).toBe(1));
  });

  it("manage_members absent → member/team controls omitted from the DOM (4.4)", () => {
    renderView(<MembersView />, "viewer");
    expect(screen.getByTestId("members-view")).toBeInTheDocument();
    expect(screen.queryByTestId("add-member-card")).toBeNull();
    expect(screen.queryByTestId("create-team-card")).toBeNull();
    expect(screen.queryByTestId("add-member-submit")).toBeNull();
  });

  it("manage_api_keys present → API-key controls in DOM and wired to /orgs/* (4.5)", async () => {
    let listCalls = 0;
    let createCalls = 0;
    server.use(
      http.get(`${BASE}/orgs/org-1/api-keys`, () => {
        listCalls += 1;
        return HttpResponse.json([]);
      }),
      http.post(`${BASE}/orgs/org-1/api-keys`, async ({ request }) => {
        createCalls += 1;
        const body = (await request.json()) as { role: Role };
        return HttpResponse.json(
          {
            api_key_id: "key-1",
            key_prefix: "af_live_ab",
            role: body.role,
            secret: "af_live_ab_SUPERSECRET",
          },
          { status: 201 },
        );
      }),
    );

    renderView(<ApiKeysView />, "admin");
    // List query fired under /orgs/{org_id}/api-keys.
    await waitFor(() => expect(listCalls).toBe(1));
    // Create control present.
    expect(screen.getByTestId("create-api-key")).toBeInTheDocument();

    // Wired to POST /orgs/{org_id}/api-keys; secret shown once.
    const user = userEvent.setup();
    await user.click(screen.getByTestId("create-api-key"));
    await waitFor(() => expect(createCalls).toBe(1));
    await waitFor(() =>
      expect(screen.getByTestId("secret-value")).toHaveTextContent(
        "af_live_ab_SUPERSECRET",
      ),
    );
  });

  it("manage_api_keys absent → API-key controls omitted from the DOM (4.5)", () => {
    renderView(<ApiKeysView />, "viewer");
    expect(screen.getByTestId("api-keys-view")).toBeInTheDocument();
    expect(screen.queryByTestId("create-api-key")).toBeNull();
    expect(screen.queryByTestId("api-keys-list")).toBeNull();
  });
});
