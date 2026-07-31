// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { axe } from "vitest-axe";
import { toHaveNoViolations } from "vitest-axe/dist/matchers.js";

// vitest-axe ships its type augmentation for an older Vitest `Vi` namespace;
// declare the matcher against Vitest's `Assertion` interface directly.
declare module "vitest" {
  // Must match Vitest's own `Assertion<T = any>` type-parameter signature.
  interface Assertion<T = any> {
    toHaveNoViolations(): T;
  }
  interface AsymmetricMatchersContaining {
    toHaveNoViolations(): void;
  }
}

import { MembersView } from "./MembersView";
import { ApiKeysView } from "./ApiKeysView";
import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import { ToastProvider } from "../../providers/ToastProvider";
import type { Role } from "../../auth/token";
import { type ReactNode } from "react";

const BASE = "http://localhost:8000";
const server = setupServer();

expect.extend({ toHaveNoViolations });

// jsdom computes no layout, so contrast is unverifiable here (the Playwright axe
// lane covers it in a real browser); `region` is not meaningful for a subtree
// rendered without the app shell's landmarks.
const AXE_OPTIONS = {
  rules: {
    "color-contrast": { enabled: false },
    region: { enabled: false },
  },
};

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderView(ui: ReactNode, role: Role): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <SessionContext.Provider value={makeSession(role)}>
          {ui}
        </SessionContext.Provider>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

/** The roster/teams reads `MembersView` performs on mount, mocked as empty. */
function mockEmptyAdminLists(): void {
  server.use(
    http.get(`${BASE}/orgs/org-1/members`, () => HttpResponse.json([])),
    http.get(`${BASE}/orgs/org-1/teams`, () => HttpResponse.json([])),
  );
}

/**
 * Task 16.1 — RBAC gating of org member/team + API-key management.
 * _Requirements: 4.4, 4.5_
 */
describe("org management gating (MSW)", () => {
  it("manage_members present → member/team controls in DOM and wired to /orgs/* (4.4)", async () => {
    let addMemberCalls = 0;
    mockEmptyAdminLists();
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

  it("renders the roster and reassigns a role through PATCH /orgs/{id}/members/{uid}", async () => {
    let patched: { user_id: string; role: Role } | null = null;
    server.use(
      http.get(`${BASE}/orgs/org-1/members`, () =>
        HttpResponse.json([
          {
            user_id: "u1",
            email: "owner@example.com",
            role: "owner",
            created_at: "2026-07-01T00:00:00Z",
          },
          {
            user_id: "u2",
            email: "member@example.com",
            role: "member",
            created_at: "2026-07-02T00:00:00Z",
          },
        ]),
      ),
      http.get(`${BASE}/orgs/org-1/teams`, () => HttpResponse.json([])),
      http.patch(`${BASE}/orgs/org-1/members/u2`, async ({ request }) => {
        const body = (await request.json()) as { role: Role };
        patched = { user_id: "u2", role: body.role };
        return HttpResponse.json({
          user_id: "u2",
          email: "member@example.com",
          role: body.role,
          created_at: "2026-07-02T00:00:00Z",
        });
      }),
    );

    renderView(<MembersView />, "owner");

    await waitFor(() =>
      expect(screen.getByTestId("members-list")).toBeInTheDocument(),
    );
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("member@example.com")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("member-role-trigger-u2"));
    await user.click(screen.getByTestId("set-role-u2-admin"));

    await waitFor(() => expect(patched).toEqual({ user_id: "u2", role: "admin" }));
  });

  it("surfaces the backend last_owner refusal instead of pre-empting it", async () => {
    server.use(
      http.get(`${BASE}/orgs/org-1/members`, () =>
        HttpResponse.json([
          {
            user_id: "u1",
            email: "owner@example.com",
            role: "owner",
            created_at: "2026-07-01T00:00:00Z",
          },
        ]),
      ),
      http.get(`${BASE}/orgs/org-1/teams`, () => HttpResponse.json([])),
      http.delete(`${BASE}/orgs/org-1/members/u1`, () =>
        HttpResponse.json(
          {
            error: {
              code: "last_owner",
              message: "An organization must always retain at least one owner.",
              details: { org_id: "org-1" },
            },
          },
          { status: 400 },
        ),
      ),
    );

    renderView(<MembersView />, "owner");
    await waitFor(() =>
      expect(screen.getByTestId("members-list")).toBeInTheDocument(),
    );

    const user = userEvent.setup();
    await user.click(screen.getByTestId("remove-member-u1"));
    await user.click(screen.getByTestId("confirm-remove-member-u1"));

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toHaveTextContent(
        "at least one owner",
      ),
    );
    // The member is still listed: nothing was optimistically removed.
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
  });

  it("lists a team's members and removes one through DELETE", async () => {
    let removed = 0;
    server.use(
      http.get(`${BASE}/orgs/org-1/members`, () => HttpResponse.json([])),
      http.get(`${BASE}/orgs/org-1/teams`, () =>
        HttpResponse.json([
          { team_id: "t1", name: "Platform", created_at: "2026-07-01T00:00:00Z" },
        ]),
      ),
      http.get(`${BASE}/orgs/org-1/teams/t1/members`, () =>
        HttpResponse.json(
          removed === 0
            ? [
                {
                  user_id: "u2",
                  email: "member@example.com",
                  created_at: "2026-07-02T00:00:00Z",
                },
              ]
            : [],
        ),
      ),
      http.delete(`${BASE}/orgs/org-1/teams/t1/members/u2`, () => {
        removed += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderView(<MembersView />, "owner");

    await waitFor(() =>
      expect(screen.getByTestId("team-members-list")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("team-detail-card")).toHaveTextContent("Platform");

    const user = userEvent.setup();
    await user.click(screen.getByTestId("remove-team-member-u2"));

    await waitFor(() => expect(removed).toBe(1));
    await waitFor(() =>
      expect(screen.getByTestId("team-members-empty")).toBeInTheDocument(),
    );
  });

  it("binds the team detail card to the team just created, not to the first one", async () => {
    // The regression this guards: the selection used to fall back to `teamList[0]`
    // whenever the picked id was absent from the cached list — exactly the state a
    // fresh create produces — so the detail card, its member list, and the
    // "Add to team" write all targeted a different, pre-existing team. The refetch
    // after the create is made to FAIL here, because queries do not retry: that is
    // the case where the wrong selection used to persist indefinitely behind a
    // "Team created" toast.
    const addedTo: string[] = [];
    let teamListRequests = 0;
    server.use(
      http.get(`${BASE}/orgs/org-1/members`, () => HttpResponse.json([])),
      http.get(`${BASE}/orgs/org-1/teams`, () => {
        teamListRequests += 1;
        if (teamListRequests > 1) {
          return HttpResponse.json(
            { error: { code: "internal_error", message: "boom", details: {} } },
            { status: 500 },
          );
        }
        return HttpResponse.json([
          { team_id: "t1", name: "Existing", created_at: "2026-07-01T00:00:00Z" },
        ]);
      }),
      http.get(`${BASE}/orgs/org-1/teams/:teamId/members`, () => HttpResponse.json([])),
      http.post(`${BASE}/orgs/org-1/teams`, () =>
        HttpResponse.json(
          { team_id: "t2", name: "Fresh", created_at: "2026-07-31T00:00:00Z" },
          { status: 201 },
        ),
      ),
      http.post(`${BASE}/orgs/org-1/teams/:teamId/members`, ({ params }) => {
        addedTo.push(String(params.teamId));
        return HttpResponse.json({ team_id: params.teamId, user_id: "u9" }, { status: 201 });
      }),
    );

    renderView(<MembersView />, "owner");
    await waitFor(() => expect(screen.getByTestId("teams-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Team name"), "Fresh");
    await user.click(screen.getByTestId("create-team-submit"));

    // The created team is selected and shown, even though the list refetch that
    // followed failed outright.
    await waitFor(() =>
      expect(screen.getByTestId("team-detail-card")).toHaveTextContent("Fresh"),
    );

    await user.type(screen.getByLabelText("Add a member to this team"), "u@example.com");
    await user.click(screen.getByTestId("add-team-member-submit"));

    // The write went to the team the operator created, not to "Existing".
    await waitFor(() => expect(addedTo).toEqual(["t2"]));
  });

  it("deletes a team after confirmation", async () => {
    let deleted = 0;
    server.use(
      http.get(`${BASE}/orgs/org-1/members`, () => HttpResponse.json([])),
      http.get(`${BASE}/orgs/org-1/teams`, () =>
        HttpResponse.json(
          deleted === 0
            ? [{ team_id: "t1", name: "Platform", created_at: "2026-07-01T00:00:00Z" }]
            : [],
        ),
      ),
      http.get(`${BASE}/orgs/org-1/teams/t1/members`, () => HttpResponse.json([])),
      http.delete(`${BASE}/orgs/org-1/teams/t1`, () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderView(<MembersView />, "owner");
    await waitFor(() => expect(screen.getByTestId("teams-list")).toBeInTheDocument());

    const user = userEvent.setup();
    await user.click(screen.getByTestId("delete-team-t1"));
    await user.click(screen.getByTestId("confirm-delete-team-t1"));

    await waitFor(() => expect(deleted).toBe(1));
    await waitFor(() => expect(screen.queryByTestId("teams-list")).toBeNull());
  });

  it("manage_members absent → member/team controls omitted from the DOM (4.4)", () => {
    renderView(<MembersView />, "viewer");
    expect(screen.getByTestId("members-view")).toBeInTheDocument();
    expect(screen.queryByTestId("add-member-card")).toBeNull();
    expect(screen.queryByTestId("create-team-card")).toBeNull();
    expect(screen.queryByTestId("add-member-submit")).toBeNull();
  });

  it("the populated member/team administration surface has no axe violations", async () => {
    server.use(
      http.get(`${BASE}/orgs/org-1/members`, () =>
        HttpResponse.json([
          {
            user_id: "u1",
            email: "owner@example.com",
            role: "owner",
            created_at: "2026-07-01T00:00:00Z",
          },
        ]),
      ),
      http.get(`${BASE}/orgs/org-1/teams`, () =>
        HttpResponse.json([
          { team_id: "t1", name: "Platform", created_at: "2026-07-01T00:00:00Z" },
        ]),
      ),
      http.get(`${BASE}/orgs/org-1/teams/t1/members`, () =>
        HttpResponse.json([
          {
            user_id: "u1",
            email: "owner@example.com",
            created_at: "2026-07-02T00:00:00Z",
          },
        ]),
      ),
    );

    const { container } = renderView(<MembersView />, "owner");
    await waitFor(() =>
      expect(screen.getByTestId("team-members-list")).toBeInTheDocument(),
    );

    const results = await axe(container, AXE_OPTIONS);
    expect(results).toHaveNoViolations();
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

  it("the populated API-key surface has no axe violations", async () => {
    server.use(
      http.get(`${BASE}/orgs/org-1/api-keys`, () =>
        HttpResponse.json([
          {
            id: "key-1",
            org_id: "org-1",
            key_prefix: "af_live_",
            role: "viewer",
            created_at: "2026-07-01T00:00:00Z",
            revoked_at: null,
          },
        ]),
      ),
    );

    const { container } = renderView(<ApiKeysView />, "admin");
    await waitFor(() =>
      expect(screen.getByTestId("api-keys-list")).toBeInTheDocument(),
    );

    const results = await axe(container, AXE_OPTIONS);
    expect(results).toHaveNoViolations();
  });

  it("manage_api_keys absent → API-key controls omitted from the DOM (4.5)", () => {
    renderView(<ApiKeysView />, "viewer");
    expect(screen.getByTestId("api-keys-view")).toBeInTheDocument();
    expect(screen.queryByTestId("create-api-key")).toBeNull();
    expect(screen.queryByTestId("api-keys-list")).toBeNull();
  });
});
