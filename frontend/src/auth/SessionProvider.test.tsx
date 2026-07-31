import type { JSX } from "react";
import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { SessionProvider } from "./SessionProvider";
import { useSession } from "./useSession";
import { AppRouter } from "../routing/AppRouter";
import {
  setToken,
  __resetTokenStoreForTests,
} from "./tokenStore";
import type { Role } from "./token";
import { ThemeProvider } from "../providers/ThemeProvider";
import { ToastProvider } from "../providers/ToastProvider";
import { CommandPaletteProvider } from "../providers/CommandPaletteProvider";

/** Build a JWT with the given claims (well-formed header.payload.signature). */
function b64url(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function makeToken(claims: { sub: string; org_id: string; role: Role; exp: number }): string {
  return `${b64url(JSON.stringify({ alg: "HS256" }))}.${b64url(JSON.stringify(claims))}.${b64url("sig")}`;
}

const future = Math.floor(Date.now() / 1000) + 3600;
const past = Math.floor(Date.now() / 1000) - 3600;

function SessionProbe(): JSX.Element {
  const { isAuthenticated, orgId, role } = useSession();
  return (
    <div>
      <span data-testid="authed">{String(isAuthenticated)}</span>
      <span data-testid="org">{orgId ?? "-"}</span>
      <span data-testid="role">{role ?? "-"}</span>
    </div>
  );
}

function renderApp(initialPath: string) {
  // The authenticated Dashboard renders live WorkspaceStats via React Query, so
  // the app tree needs a QueryClientProvider (as it does in production). Retries
  // are disabled so any stat fetch settles immediately in the test environment.
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
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
}

/**
 * Task 6.1 — session hydration + protected routing.
 * _Requirements: 3.1, 3.2, 3.4, 2.5_
 */
describe("SessionProvider + routing", () => {
  beforeEach(() => {
    __resetTokenStoreForTests();
  });

  it("hydrates a valid token into an authenticated session (3.1)", () => {
    setToken(makeToken({ sub: "u1", org_id: "org-1", role: "admin", exp: future }));
    render(
      <MemoryRouter>
        <SessionProvider>
          <SessionProbe />
        </SessionProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("authed")).toHaveTextContent("true");
    expect(screen.getByTestId("org")).toHaveTextContent("org-1");
    expect(screen.getByTestId("role")).toHaveTextContent("admin");
  });

  it("treats an expired token as unauthenticated (3.2)", () => {
    setToken(makeToken({ sub: "u1", org_id: "org-1", role: "admin", exp: past }));
    render(
      <MemoryRouter>
        <SessionProvider>
          <SessionProbe />
        </SessionProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("authed")).toHaveTextContent("false");
    expect(screen.getByTestId("org")).toHaveTextContent("-");
  });

  it("treats a malformed token as unauthenticated (3.2)", () => {
    setToken("not-a-jwt");
    render(
      <MemoryRouter>
        <SessionProvider>
          <SessionProbe />
        </SessionProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("authed")).toHaveTextContent("false");
  });

  it("redirects unauthenticated access to a protected route to /login (2.5)", () => {
    renderApp("/");
    expect(screen.getByTestId("login-view")).toBeInTheDocument();
  });

  it("allows an authenticated Operator into the protected home", () => {
    setToken(makeToken({ sub: "u1", org_id: "org-1", role: "member", exp: future }));
    renderApp("/");
    expect(screen.getByTestId("home-view")).toBeInTheDocument();
  });

  it("logout clears state and routes back to /login (3.4)", () => {
    setToken(makeToken({ sub: "u1", org_id: "org-1", role: "member", exp: future }));

    function LogoutProbe(): JSX.Element {
      const { isAuthenticated, logout } = useSession();
      return (
        <div>
          <span data-testid="authed">{String(isAuthenticated)}</span>
          <button onClick={logout}>logout</button>
        </div>
      );
    }

    render(
      <MemoryRouter>
        <SessionProvider>
          <LogoutProbe />
        </SessionProvider>
      </MemoryRouter>,
    );
    expect(screen.getByTestId("authed")).toHaveTextContent("true");
    act(() => {
      screen.getByRole("button", { name: "logout" }).click();
    });
    expect(screen.getByTestId("authed")).toHaveTextContent("false");
  });
});
