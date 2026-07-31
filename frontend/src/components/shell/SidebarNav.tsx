/**
 * `SidebarNav`: the RBAC-aware, grouped navigation list.
 *
 * Renders one entry per `NAV_ITEMS` destination, each wrapped in the `Can` gate
 * so an unauthorized destination is **absent from the DOM** (not merely
 * disabled). Entries are organized into labeled sections (`NAV_GROUP_ORDER`);
 * a section renders only when at least one of its entries is permitted. The
 * active entry carries a left accent bar and raised surface. Used by both the
 * persistent desktop sidebar and the mobile drawer.
 */
import type { JSX } from "react";
import { useEffect, useRef } from "react";
import { NavLink } from "react-router";

import { Can } from "../Can";
import { useSession } from "../../auth/useSession";
import { can } from "../../auth/rbac";
import { NAV_ITEMS, NAV_GROUP_ORDER, type NavItem, type NavGroup } from "../../routing/navItems";
import { cn } from "../../lib/cn";

function NavEntry({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  onNavigate?: () => void;
}): JSX.Element {
  const Icon = item.icon;
  const ref = useRef<HTMLAnchorElement>(null);

  /*
   * Twelve destinations in four groups do not fit a short viewport however tight
   * the spacing, so the list scrolls — and the entry for the page you are on was
   * as likely as not to be the one scrolled out of sight, leaving the nav with no
   * indication of where you were.
   *
   * The container's `scrollTop` is adjusted directly rather than by calling
   * `scrollIntoView`, which in Chromium also moves the *sequential focus
   * navigation starting point* to the scrolled element. That silently broke the
   * skip link: the first Tab landed on the nav entry after the active one instead
   * of on the skip link, defeating WCAG 2.4.1. Setting `scrollTop` scrolls
   * without touching focus.
   */
  useEffect(() => {
    const node = ref.current;
    if (!node || node.getAttribute("aria-current") !== "page") return;
    const container = node.closest<HTMLElement>("[data-nav-scroll]");
    if (!container) return;

    const entry = node.getBoundingClientRect();
    const view = container.getBoundingClientRect();
    // Only move when the entry is actually outside the visible band, so
    // navigating between two visible entries never jumps the list.
    if (entry.top < view.top) {
      container.scrollTop -= view.top - entry.top;
    } else if (entry.bottom > view.bottom) {
      container.scrollTop += entry.bottom - view.bottom;
    }
  });

  return (
    <NavLink
      ref={ref}
      to={item.path}
      end={item.path === "/"}
      onClick={onNavigate}
      data-testid={`nav-${item.id}`}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          // py-1.5 rather than py-2: four rows' worth of height across the list,
          // which is the difference between fitting a laptop viewport and not.
          "group relative flex items-center gap-3 rounded-md px-3 py-1.5 text-sm font-medium transition-colors duration-fast",
          "text-text-muted hover:bg-surface-hover hover:text-text",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
          isActive && "bg-surface-raised text-text",
          collapsed && "justify-center px-2",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && !collapsed && (
            <span
              aria-hidden="true"
              className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-full bg-primary"
            />
          )}
          <Icon
            className={cn(
              "h-4 w-4 shrink-0 transition-colors",
              isActive ? "text-primary" : "text-text-muted group-hover:text-text",
            )}
            aria-hidden="true"
          />
          {!collapsed && <span className="truncate">{item.label}</span>}
        </>
      )}
    </NavLink>
  );
}

export function SidebarNav({
  collapsed = false,
  onNavigate,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
}): JSX.Element {
  const { role } = useSession();

  const isPermitted = (item: NavItem): boolean =>
    item.permission === null || (role !== null && can(role, item.permission));

  const sections = NAV_GROUP_ORDER.map((group) => ({
    group,
    items: NAV_ITEMS.filter((item) => item.group === group),
  })).filter((section) => section.items.some(isPermitted));

  return (
    <nav
      aria-label="Primary"
      data-testid="sidebar-nav"
      className="flex flex-col gap-3"
    >
      {sections.map(({ group, items }) => (
        <NavSection
          key={group}
          group={group}
          items={items}
          collapsed={collapsed}
          onNavigate={onNavigate}
        />
      ))}
    </nav>
  );
}

function NavSection({
  group,
  items,
  collapsed,
  onNavigate,
}: {
  group: NavGroup;
  items: readonly NavItem[];
  collapsed: boolean;
  onNavigate?: () => void;
}): JSX.Element {
  return (
    <div className="flex flex-col gap-1">
      {collapsed ? (
        <div className="mx-auto my-1 h-px w-6 bg-border" aria-hidden="true" />
      ) : (
        <span className="px-3 pb-0.5 text-[0.65rem] font-semibold uppercase tracking-wide text-text-subtle">
          {group}
        </span>
      )}
      {items.map((item) =>
        item.permission === null ? (
          <NavEntry
            key={item.id}
            item={item}
            collapsed={collapsed}
            onNavigate={onNavigate}
          />
        ) : (
          <Can key={item.id} permission={item.permission}>
            <NavEntry item={item} collapsed={collapsed} onNavigate={onNavigate} />
          </Can>
        ),
      )}
    </div>
  );
}
