/**
 * Shared RBAC-aware navigation destinations.
 *
 * A single source of truth for the app-shell sidebar nav and the ⌘K command
 * palette's navigation commands, so both gate identical destinations by the
 * same `can(role, permission)` decision. Each entry declares the `Permission`
 * required to reach it; an entry with `permission: null` is reachable by any
 * authenticated Session.
 */
import {
  BarChart3,
  Bot,
  ClipboardCheck,
  FileText,
  KeyRound,
  LayoutDashboard,
  MessagesSquare,
  Plug,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { Permission } from "../auth/rbac";

/** Sidebar section a destination belongs to (display grouping only). */
export type NavGroup = "Workspace" | "Agents" | "Platform" | "Administration";

/** Ordered section headings for the sidebar. */
export const NAV_GROUP_ORDER: readonly NavGroup[] = [
  "Workspace",
  "Agents",
  "Platform",
  "Administration",
];

/** A navigable destination in the authenticated app. */
export interface NavItem {
  /** Stable id (used for keys and command ids). */
  id: string;
  /** Route path. */
  path: string;
  /** Sidebar / command label. */
  label: string;
  /** Icon for the sidebar and palette. */
  icon: LucideIcon;
  /** Permission required to see/reach the destination (`null` = any session). */
  permission: Permission | null;
  /** Sidebar section grouping. */
  group: NavGroup;
}

/** The canonical navigation destinations, in display order. */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    id: "nav-dashboard",
    path: "/",
    label: "Dashboard",
    icon: LayoutDashboard,
    permission: "read",
    group: "Workspace",
  },
  {
    id: "nav-query",
    path: "/query",
    label: "Query",
    icon: Search,
    permission: "run_agents",
    group: "Workspace",
  },
  {
    id: "nav-documents",
    path: "/documents",
    label: "Documents",
    icon: FileText,
    permission: "read",
    group: "Workspace",
  },
  {
    id: "nav-conversations",
    path: "/conversations",
    label: "Conversations",
    icon: MessagesSquare,
    permission: "read",
    group: "Workspace",
  },
  {
    id: "nav-agent",
    path: "/agents",
    label: "Agent Runs",
    icon: Bot,
    permission: "run_agents",
    group: "Agents",
  },
  {
    id: "nav-multi-agent",
    path: "/multi-agent",
    label: "Multi-Agent",
    icon: Sparkles,
    permission: "run_agents",
    group: "Agents",
  },
  {
    id: "nav-prompts",
    path: "/prompts",
    label: "Prompts",
    icon: SlidersHorizontal,
    permission: "read",
    group: "Platform",
  },
  {
    id: "nav-analytics",
    path: "/analytics",
    label: "Analytics",
    icon: BarChart3,
    permission: "read",
    group: "Platform",
  },
  {
    id: "nav-guardrails",
    path: "/guardrails",
    label: "Guardrails",
    icon: ShieldCheck,
    permission: "read",
    group: "Platform",
  },
  {
    id: "nav-evaluations",
    path: "/evaluations",
    label: "Evaluations",
    icon: ClipboardCheck,
    permission: "read",
    group: "Platform",
  },
  {
    id: "nav-integrations",
    path: "/integrations",
    label: "Integrations",
    icon: Plug,
    permission: "read",
    group: "Platform",
  },
  {
    id: "nav-members",
    path: "/members",
    label: "Members & Teams",
    icon: Users,
    permission: "manage_members",
    group: "Administration",
  },
  {
    id: "nav-api-keys",
    path: "/api-keys",
    label: "API Keys",
    icon: KeyRound,
    permission: "manage_api_keys",
    group: "Administration",
  },
];
