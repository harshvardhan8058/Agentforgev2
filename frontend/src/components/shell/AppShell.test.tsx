import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";

import { AppShell } from "./AppShell";
import { SessionContext, type SessionApi } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";
import { ThemeProvider } from "../../providers/ThemeProvider";
import { CommandPaletteProvider } from "../../providers/CommandPaletteProvider";
import {
  rememberOrgToken,
  __resetOrgTokenStoreForTests,
} from "../../auth/orgTokenStore";

/** Base64url-encode a JSON payload (jsdom `btoa`). */
function b64url(obj: unknown): string {
  return btoa(JSON.stringify(obj))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

/** Craft a decodable JWT for a given org/role. */
function makeJwt(orgId: string, role: Role): string {
  return `${b64url({ alg: "none" })}.${b64url({
    sub: "u1",
    org_id: orgId,
    role,
    exp: 9_999_999_999,
  })}.sig`;
}

/** Install a matchMedia stub that reports desktop/mobile for width queries. */
function mockMatchMedia(desktop: boolean): void {
  window.matchMedia = ((query: string) => {
    const reduced = /prefers-reduced-motion/.test(query);
    const minWidth = /min-width/.test(query);
    return {
      matches: reduced ? true : minWidth ? desktop : false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    };
  }) as unknown as typeof window.matchMedia;
}

function renderShell(session: SessionApi): void {
  render(
    <ThemeProvider>
      <CommandPaletteProvider>
        <MemoryRouter initialEntries={["/"]}>
          <SessionContext.Provider value={session}>
            <AppShell>
              <div data-testid="content">page</div>
            </AppShell>
          </SessionContext.Provider>
        </MemoryRouter>
      </CommandPaletteProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  __resetOrgTokenStoreForTests();
  localStorage.clear();
  mockMatchMedia(true);
});

afterEach(() => {
  mockMatchMedia(true);
});

describe("AppShell — RBAC-aware, responsive shell (Req 4.1, 4.6)", () => {
  it("renders the Org badge with the active Org_Context and Role (4.1)", () => {
    renderShell(makeSession("admin"));
    expect(screen.getByTestId("org-context-org")).toHaveTextContent("org-1");
    expect(screen.getByTestId("org-context-role")).toHaveTextContent("admin");
  });

  it("shows nav entries only when can() grants them", () => {
    renderShell(makeSession("viewer"));
    // viewer has `read`
    expect(screen.getByTestId("nav-nav-dashboard")).toBeInTheDocument();
    expect(screen.getByTestId("nav-nav-documents")).toBeInTheDocument();
    // viewer lacks run_agents / manage_*
    expect(screen.queryByTestId("nav-nav-query")).toBeNull();
    expect(screen.queryByTestId("nav-nav-members")).toBeNull();
    expect(screen.queryByTestId("nav-nav-api-keys")).toBeNull();
  });

  it("shows run/manage nav entries for an owner", () => {
    renderShell(makeSession("owner"));
    expect(screen.getByTestId("nav-nav-query")).toBeInTheDocument();
    expect(screen.getByTestId("nav-nav-members")).toBeInTheDocument();
    expect(screen.getByTestId("nav-nav-api-keys")).toBeInTheDocument();
  });

  it("org switch adopts the stored token whose org_id matches the selection (4.6)", async () => {
    const tokenOrg1 = makeJwt("org-1", "owner");
    const tokenOrg2 = makeJwt("org-2", "admin");
    rememberOrgToken(tokenOrg1);
    rememberOrgToken(tokenOrg2);

    const login = vi.fn();
    const session: SessionApi = { ...makeSession("owner"), login };
    renderShell(session);

    const user = userEvent.setup();
    await user.click(screen.getByTestId("org-switcher-trigger"));
    const option = await screen.findByTestId("org-option-org-2");
    await user.click(option);

    await waitFor(() => expect(login).toHaveBeenCalledWith(tokenOrg2));
  });

  it("theme toggle flips data-theme", async () => {
    renderShell(makeSession("member"));
    const before = document.documentElement.getAttribute("data-theme");
    fireEvent.click(screen.getByTestId("theme-toggle"));
    await waitFor(() => {
      const after = document.documentElement.getAttribute("data-theme");
      expect(after).not.toBe(before);
      expect(["dark", "light"]).toContain(after);
    });
  });

  it("renders a persistent sidebar at md+ and no mobile trigger", () => {
    mockMatchMedia(true);
    renderShell(makeSession("owner"));
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.queryByTestId("mobile-nav-trigger")).toBeNull();
  });

  it("collapses to a mobile drawer below md", async () => {
    mockMatchMedia(false);
    renderShell(makeSession("owner"));
    expect(screen.queryByTestId("sidebar")).toBeNull();
    const trigger = screen.getByTestId("mobile-nav-trigger");
    expect(trigger).toBeInTheDocument();
    fireEvent.click(trigger);
    await waitFor(() =>
      expect(screen.getByTestId("mobile-drawer")).toBeInTheDocument(),
    );
  });
});
