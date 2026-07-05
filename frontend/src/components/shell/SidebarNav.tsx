/**
 * `SidebarNav`: the RBAC-aware navigation list.
 *
 * Renders one entry per `NAV_ITEMS` destination, each wrapped in the `Can` gate
 * so an unauthorized destination is **absent from the DOM** (not merely
 * disabled). Used by both the persistent desktop sidebar and the mobile drawer.
 */
import { NavLink } from "react-router-dom";

import { Can } from "../Can";
import { NAV_ITEMS, type NavItem } from "../../routing/navItems";
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
  return (
    <NavLink
      to={item.path}
      end={item.path === "/"}
      onClick={onNavigate}
      data-testid={`nav-${item.id}`}
      title={collapsed ? item.label : undefined}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
          "text-text-muted hover:bg-surface-raised hover:text-text",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring",
          isActive && "bg-surface-raised text-text",
          collapsed && "justify-center px-2",
        )
      }
    >
      <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
      {!collapsed && <span className="truncate">{item.label}</span>}
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
  return (
    <nav
      aria-label="Primary"
      data-testid="sidebar-nav"
      className="flex flex-col gap-1"
    >
      {NAV_ITEMS.map((item) =>
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
    </nav>
  );
}
