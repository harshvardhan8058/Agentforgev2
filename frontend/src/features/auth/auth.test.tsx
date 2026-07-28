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
import {
  getToken,
  setToken,
  __resetTokenStoreForTests,
} from "../../auth/tokenStore";
import { __resetOrgTokenStoreForTests } from "../../auth/orgTokenStore";
import type { Role } from "../../auth/token";

const BASE = "http://localhost:8000";
// The authenticated Dashboard (home-view) renders live WorkspaceStats, which
// fetch GET /documents and GET /analytics/usage. Default no-op handlers keep
// these auth-flow tests green under the strict onUnhandledRequest guard.
const server = setupServer(
  http.get(`${BASE}/documents`, () => HttpResponse.json([])),
  http.get(`${BASE}/analytics/usage`, () =>
    HttpResponse.json({
      org_id: "org-1",
      start: null,
      end: null,
      total_tokens: 0,
      total_cost: "0",
      by_provider: [],
      by_model: [],
      by_user: [],
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  __resetTokenStoreForTests();
  __resetOrgTokenStoreForTests();
  localStorage.clear();
});
afterAll(() => server.close());

/** Base64url-encode a JSON payload. */
function b64url(obj: unknown): string {
  return btoa(JSON.stringify(obj))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}
/** A decodable, non-expired JWT for a given org/role. */
function makeJwt(orgId: string, role: Role): string {
  return `${b64url({ alg: "HS256" })}.${b64url({
    sub: "u1",
    org_id: orgId,
    role,
    exp: 9_999_999_999,
  })}.sig`;
}

function renderApp(initialPath: string): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <ThemeProvider>
      <ToastProvider>
        <CommandPaletteProvider>
          <QueryClientProvider client={queryClient}>
            <SessionProvider>
              <MemoryRouter initialEntries={[initialPath]}>
                <AppRouter />
              </MemoryRouter>
            </SessionProvider>
          </QueryClientProvider>
        </CommandPaletteProvider>
      </ToastProvider>
    </ThemeProvider>,
  );
  return queryClient;
}

/**
 * Task 14.1 — auth flows (MSW).
 * _Requirements: 2.1, 2.2, 2.3, 2.4, 3.4_
 */
describe("auth views (MSW)", () => {
  it("login stores the returned token and routes into the console (2.1)", async () => {
    const token = makeJwt("org-1", "admin");
    server.use(
      http.post(`${BASE}/auth/login`, async ({ request }) => {
        const body = (await request.json()) as { email: string; password: string };
        expect(body.email).toBe("ada@example.com");
        expect(body.password).toBe("s3cret");
        return HttpResponse.json({ access_token: token, token_type: "bearer" });
      }),
    );

    renderApp("/login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "s3cret");
    await user.click(screen.getByTestId("login-submit"));

    await waitFor(() => expect(getToken()).toBe(token));
    // Routed to the authenticated dashboard.
    await waitFor(() => expect(screen.getByTestId("home-view")).toBeInTheDocument());
  });

  it("401 auth_failed shows the envelope message and stays on login (2.2)", async () => {
    server.use(
      http.post(`${BASE}/auth/login`, () =>
        HttpResponse.json(
          { error: { code: "auth_failed", message: "Invalid email or password.", details: {} } },
          { status: 401 },
        ),
      ),
    );

    renderApp("/login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "ada@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByTestId("login-submit"));

    await waitFor(() =>
      expect(screen.getByTestId("error-message")).toHaveTextContent(
        "Invalid email or password.",
      ),
    );
    expect(screen.getByTestId("login-view")).toBeInTheDocument();
    expect(getToken()).toBeNull();
  });

  it("blocks login submission with an empty email or password (2.4)", async () => {
    let calls = 0;
    server.use(
      http.post(`${BASE}/auth/login`, () => {
        calls += 1;
        return HttpResponse.json({ access_token: "x", token_type: "bearer" });
      }),
    );

    renderApp("/login");
    const user = userEvent.setup();
    // Submit with both fields empty — no request, validation shown, stays on login.
    await user.click(screen.getByTestId("login-submit"));
    expect(calls).toBe(0);
    expect(screen.getByTestId("login-view")).toBeInTheDocument();
    expect(screen.getByText("Enter your email to continue.")).toBeInTheDocument();
    expect(screen.getByText("Enter your password to continue.")).toBeInTheDocument();
  });

  it("register 201 stores the returned token (2.3)", async () => {
    const token = makeJwt("org-9", "owner");
    server.use(
      http.post(`${BASE}/auth/register-self`, async ({ request }) => {
        const body = (await request.json()) as {
          email: string;
          password: string;
          org_name: string;
        };
        expect(body.org_name).toBe("Acme");
        expect(body.email).toBe("new@example.com");
        return HttpResponse.json(
          { access_token: token, token_type: "bearer" },
          { status: 201 },
        );
      }),
    );

    renderApp("/register");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Organization name"), "Acme");
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "sup3rSecret");
    await user.click(screen.getByTestId("register-submit"));

    await waitFor(() => expect(getToken()).toBe(token));
    await waitFor(() => expect(screen.getByTestId("home-view")).toBeInTheDocument());
  });

  it("blocks register submission while any field is empty (2.4)", async () => {
    let calls = 0;
    server.use(
      http.post(`${BASE}/auth/register-self`, () => {
        calls += 1;
        return HttpResponse.json({ access_token: "x", token_type: "bearer" }, { status: 201 });
      }),
    );

    renderApp("/register");
    const user = userEvent.setup();
    await user.click(screen.getByTestId("register-submit"));
    expect(calls).toBe(0);
    expect(screen.getByTestId("register-view")).toBeInTheDocument();
    expect(screen.getByText("Enter an organization name to continue.")).toBeInTheDocument();
  });

  it("logout clears the token and routes back to /login (3.4)", async () => {
    setToken(makeJwt("org-1", "owner"));
    renderApp("/");
    // Authenticated: dashboard shown within the shell.
    expect(screen.getByTestId("home-view")).toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(screen.getByTestId("logout-button"));

    await waitFor(() => expect(getToken()).toBeNull());
    await waitFor(() => expect(screen.getByTestId("login-view")).toBeInTheDocument());
  });
});
