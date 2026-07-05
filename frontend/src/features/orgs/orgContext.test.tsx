// @vitest-environment jsdom
import { describe, it, expect, beforeAll, afterAll, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

import { AppRouter } from "../../routing/AppRouter";
import { SessionProvider } from "../../auth/SessionProvider";
import { ThemeProvider } from "../../providers/ThemeProvider";
import { ToastProvider } from "../../providers/ToastProvider";
import { CommandPaletteProvider } from "../../providers/CommandPaletteProvider";
import { setToken, __resetTokenStoreForTests } from "../../auth/tokenStore";
import {
  rememberOrgToken,
  __resetOrgTokenStoreForTests,
} from "../../auth/orgTokenStore";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
const server = setupServer();

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  __resetTokenStoreForTests();
  __resetOrgTokenStoreForTests();
  localStorage.clear();
});
afterAll(() => server.close());

function b64url(obj: unknown): string {
  return btoa(JSON.stringify(obj))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
function makeJwt(orgId: string, role: Role): string {
  return `${b64url({ alg: "HS256" })}.${b64url({
    sub: "u1",
    org_id: orgId,
    role,
    exp: 9_999_999_999,
  })}.sig`;
}

function apiKey(id: string, prefix: string): unknown {
  return {
    id,
    org_id: "x",
    key_prefix: prefix,
    role: "viewer",
    created_at: "2024-01-01T00:00:00Z",
    revoked_at: null,
  };
}

function renderAppAt(path: string): void {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <ThemeProvider>
      <ToastProvider>
        <CommandPaletteProvider>
          <QueryClientProvider client={queryClient}>
            <SessionProvider>
              <MemoryRouter initialEntries={[path]}>
                <AppRouter />
              </MemoryRouter>
            </SessionProvider>
          </QueryClientProvider>
        </CommandPaletteProvider>
      </ToastProvider>
    </ThemeProvider>,
  );
}

/**
 * Task 15.1 — org context, RBAC layout, and org switching.
 * _Requirements: 4.1, 4.6, 4.7_
 */
describe("org context + switching (MSW)", () => {
  it("shows the Org_Context + Role badge in the authenticated layout (4.1)", async () => {
    setToken(makeJwt("org-1", "owner"));
    server.use(
      http.get(`${BASE}/orgs/org-1/api-keys`, () => HttpResponse.json([])),
    );
    renderAppAt("/api-keys");
    expect(screen.getByTestId("org-context-org")).toHaveTextContent("org-1");
    expect(screen.getByTestId("org-context-role")).toHaveTextContent("owner");
  });

  it("org switch adopts the matching-org_id token and re-scopes queries (4.6)", async () => {
    const token1 = makeJwt("org-1", "owner");
    const token2 = makeJwt("org-2", "owner");
    rememberOrgToken(token1);
    rememberOrgToken(token2);
    setToken(token1);

    server.use(
      http.get(`${BASE}/orgs/org-1/api-keys`, () =>
        HttpResponse.json([apiKey("k1", "org1pref")]),
      ),
      http.get(`${BASE}/orgs/org-2/api-keys`, () =>
        HttpResponse.json([apiKey("k2", "org2pref")]),
      ),
    );

    renderAppAt("/api-keys");

    // Initially scoped to org-1.
    await waitFor(() =>
      expect(screen.getByTestId("api-keys-list")).toHaveTextContent("org1pref"),
    );

    // Switch to org-2 via the org switcher.
    const user = userEvent.setup();
    await user.click(screen.getByTestId("org-switcher-trigger"));
    await user.click(await screen.findByTestId("org-option-org-2"));

    // Badge now reflects org-2 and the list re-fetched under the new context.
    await waitFor(() =>
      expect(screen.getByTestId("org-context-org")).toHaveTextContent("org-2"),
    );
    await waitFor(() =>
      expect(screen.getByTestId("api-keys-list")).toHaveTextContent("org2pref"),
    );
    expect(screen.getByTestId("api-keys-list")).not.toHaveTextContent("org1pref");
  });

  it("presents a cross-tenant 404 as not-found without revealing another org (4.7)", async () => {
    setToken(makeJwt("org-1", "owner"));
    server.use(
      http.get(`${BASE}/orgs/org-1/api-keys`, () =>
        HttpResponse.json(
          {
            error: {
              code: "not_found",
              message: "The requested resource was not found.",
              details: {},
            },
          },
          { status: 404 },
        ),
      ),
    );

    renderAppAt("/api-keys");

    const banner = await screen.findByTestId("error-banner");
    expect(banner).toHaveAttribute("data-kind", "not_found");
    expect(screen.getByTestId("error-message")).toHaveTextContent(
      "The requested resource was not found.",
    );
    // No cross-org leak.
    expect(banner).not.toHaveTextContent(/org-2|another organization|exists/i);
  });
});
