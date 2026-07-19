/**
 * `AppShell`: the responsive, RBAC-aware application shell.
 *
 * A commercial-grade shell composing a collapsible sidebar, a top bar, the
 * persistent `OrgContextBadge` (active Org_Context + Role), the org switcher,
 * a theme toggle, logout, a ⌘K palette trigger, and RBAC-aware navigation
 * (each entry wrapped in `Can`). Responsive:
 *  - `< md`: the sidebar collapses into a slide-over **mobile drawer** (Radix
 *    Dialog) with the Org badge in the top bar;
 *  - `md–xl`: a persistent collapsible sidebar + content area;
 *  - `≥ 2xl`: reading surfaces honor a max-width while the shell uses the width.
 */
import * as RadixDialog from "@radix-ui/react-dialog";
import { LogOut, Menu, Moon, PanelLeft, Search, Sun } from "lucide-react";
import { useState, type ReactNode } from "react";

import { useSession } from "../../auth/useSession";
import { useTheme } from "../../hooks/useTheme";
import { useCommandPalette } from "../../hooks/useCommandPalette";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { cn } from "../../lib/cn";
import { OrgContextBadge } from "../OrgContextBadge";
import { Kbd } from "../ui/Kbd";
import { SidebarNav } from "./SidebarNav";
import { OrgSwitcher } from "./OrgSwitcher";
import { BrandLogo } from "./BrandLogo";

function BrandMark({ compact = false }: { compact?: boolean }): JSX.Element {
  return <BrandLogo compact={compact} />;
}

function ThemeToggle(): JSX.Element {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";
  return (
    <button
      type="button"
      onClick={toggleTheme}
      data-testid="theme-toggle"
      aria-label={isDark ? "Switch to light theme" : "Switch to dark theme"}
      className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted hover:bg-surface-raised hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
    >
      {isDark ? (
        <Sun className="h-4 w-4" aria-hidden="true" />
      ) : (
        <Moon className="h-4 w-4" aria-hidden="true" />
      )}
    </button>
  );
}

function CommandTrigger(): JSX.Element {
  const { openPalette } = useCommandPalette();
  return (
    <button
      type="button"
      onClick={openPalette}
      data-testid="command-trigger"
      aria-label="Open command palette"
      className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text-muted transition-colors hover:border-border-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
    >
      <Search className="h-4 w-4" aria-hidden="true" />
      <span className="hidden sm:inline">Search…</span>
      <Kbd className="ml-1 hidden sm:inline-flex">⌘K</Kbd>
    </button>
  );
}

function LogoutButton(): JSX.Element {
  const { logout } = useSession();
  return (
    <button
      type="button"
      onClick={logout}
      data-testid="logout-button"
      aria-label="Log out"
      className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted hover:bg-surface-raised hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
    >
      <LogOut className="h-4 w-4" aria-hidden="true" />
    </button>
  );
}

export function AppShell({ children }: { children: ReactNode }): JSX.Element {
  const isDesktop = useMediaQuery("(min-width: 768px)");
  const [collapsed, setCollapsed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  return (
    <div className="flex min-h-screen bg-bg text-text" data-testid="app-shell">
      {/* Persistent sidebar (md+) */}
      {isDesktop && (
        <aside
          data-testid="sidebar"
          className={cn(
            "sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-bg-subtle transition-[width] duration-base ease-standard",
            collapsed ? "w-16" : "w-64",
          )}
        >
          <div
            className={cn(
              "flex h-14 items-center border-b border-border px-4",
              collapsed && "justify-center px-2",
            )}
          >
            <BrandMark compact={collapsed} />
          </div>
          <div className="flex-1 overflow-y-auto px-3 py-4">
            <SidebarNav collapsed={collapsed} />
          </div>
          <div
            className={cn(
              "flex items-center border-t border-border p-3",
              collapsed ? "justify-center" : "justify-between",
            )}
          >
            {!collapsed && (
              <span className="px-1 text-[0.65rem] font-medium uppercase tracking-wide text-text-subtle">
                v1
              </span>
            )}
            <button
              type="button"
              onClick={() => setCollapsed((c) => !c)}
              data-testid="sidebar-collapse"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              aria-pressed={collapsed}
              className="inline-flex h-8 w-8 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
            >
              <PanelLeft
                className={cn(
                  "h-4 w-4 transition-transform duration-base",
                  collapsed && "rotate-180",
                )}
                aria-hidden="true"
              />
            </button>
          </div>
        </aside>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Top bar */}
        <header
          data-testid="top-bar"
          className="af-glass sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border px-4"
        >
          {!isDesktop && (
            <>
              <button
                type="button"
                onClick={() => setDrawerOpen(true)}
                data-testid="mobile-nav-trigger"
                aria-label="Open navigation menu"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md text-text-muted hover:bg-surface-raised hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
              >
                <Menu className="h-5 w-5" aria-hidden="true" />
              </button>
              <BrandMark compact />
            </>
          )}

          {/* On mobile the org badge lives in the top bar. */}
          {!isDesktop && <OrgContextBadge />}

          <div className="ml-auto flex items-center gap-2">
            <CommandTrigger />
            {isDesktop && <OrgContextBadge />}
            <OrgSwitcher />
            <ThemeToggle />
            <LogoutButton />
          </div>
        </header>

        {/* Routed content — reading max-width honored, dashboards may opt wider. */}
        <main
          data-testid="shell-content"
          className="mx-auto w-full max-w-screen-xl flex-1 p-4 md:p-6 2xl:max-w-screen-2xl"
        >
          {children}
        </main>
      </div>

      {/* Mobile slide-over drawer (< md) */}
      {!isDesktop && (
        <RadixDialog.Root open={drawerOpen} onOpenChange={setDrawerOpen}>
          <RadixDialog.Portal>
            <RadixDialog.Overlay className="fixed inset-0 z-40 bg-black/50" />
            <RadixDialog.Content
              data-testid="mobile-drawer"
              className="af-glass fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col gap-4 border-r border-border-strong p-4 shadow-elevation-4 focus:outline-none"
            >
              <RadixDialog.Title className="sr-only">Navigation</RadixDialog.Title>
              <RadixDialog.Description className="sr-only">
                Primary navigation
              </RadixDialog.Description>
              <BrandMark />
              <div className="-mx-1 flex-1 overflow-y-auto">
                <SidebarNav onNavigate={() => setDrawerOpen(false)} />
              </div>
            </RadixDialog.Content>
          </RadixDialog.Portal>
        </RadixDialog.Root>
      )}
    </div>
  );
}
