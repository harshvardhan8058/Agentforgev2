import { describe, it, expect } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";

import { SessionContext } from "../../auth/useSession";
import { makeSession } from "../../test/renderWithSession";
import type { Role } from "../../auth/token";
import { ThemeProvider } from "../../providers/ThemeProvider";
import { CommandPaletteProvider } from "../../providers/CommandPaletteProvider";
import { CommandLayer } from "./CommandLayer";

function LocationDisplay(): JSX.Element {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderPalette(role: Role) {
  return render(
    <ThemeProvider>
      <CommandPaletteProvider>
        <MemoryRouter initialEntries={["/"]}>
          <SessionContext.Provider value={makeSession(role)}>
            <LocationDisplay />
            <CommandLayer />
          </SessionContext.Provider>
        </MemoryRouter>
      </CommandPaletteProvider>
    </ThemeProvider>,
  );
}

/** Press ⌘K / Ctrl-K on the window (jsdom is non-mac → mod = ctrl). */
function pressModK(): void {
  fireEvent.keyDown(window, { key: "k", ctrlKey: true });
}

describe("CommandPalette — ⌘K, RBAC gating, selection, ? overlay", () => {
  it("⌘K opens the palette", async () => {
    renderPalette("owner");
    expect(screen.queryByTestId("command-cmd-nav-dashboard")).toBeNull();
    pressModK();
    await waitFor(() =>
      expect(screen.getByTestId("command-cmd-nav-dashboard")).toBeInTheDocument(),
    );
  });

  it("only surfaces commands the Session Role can perform (viewer)", async () => {
    renderPalette("viewer");
    pressModK();
    await waitFor(() =>
      expect(screen.getByTestId("command-cmd-nav-dashboard")).toBeInTheDocument(),
    );
    // viewer has only `read` (+ always-on actions): read destinations appear…
    expect(screen.getByTestId("command-cmd-nav-documents")).toBeInTheDocument();
    expect(screen.getByTestId("command-cmd-toggle-theme")).toBeInTheDocument();
    // …but run_agents / manage_* commands are absent.
    expect(screen.queryByTestId("command-cmd-nav-query")).toBeNull();
    expect(screen.queryByTestId("command-cmd-new-query")).toBeNull();
    expect(screen.queryByTestId("command-cmd-nav-members")).toBeNull();
    expect(screen.queryByTestId("command-cmd-nav-api-keys")).toBeNull();
  });

  it("surfaces run/manage commands for an owner", async () => {
    renderPalette("owner");
    pressModK();
    await waitFor(() =>
      expect(screen.getByTestId("command-cmd-nav-query")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("command-cmd-new-query")).toBeInTheDocument();
    expect(screen.getByTestId("command-cmd-nav-members")).toBeInTheDocument();
    expect(screen.getByTestId("command-cmd-nav-api-keys")).toBeInTheDocument();
  });

  it("selecting a navigation command navigates and closes the palette", async () => {
    renderPalette("owner");
    pressModK();
    const docs = await screen.findByTestId("command-cmd-nav-documents");
    fireEvent.click(docs);
    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/documents"),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("command-cmd-nav-documents")).toBeNull(),
    );
  });

  it("? opens the keyboard-shortcuts overlay", async () => {
    renderPalette("member");
    fireEvent.keyDown(window, { key: "?", shiftKey: true });
    await waitFor(() =>
      expect(screen.getByTestId("shortcuts-overlay-body")).toBeInTheDocument(),
    );
    // The overlay lists the registered chords grouped by area.
    expect(screen.getByText("Open command palette")).toBeInTheDocument();
    expect(screen.getByText("Show keyboard shortcuts")).toBeInTheDocument();
  });
});
