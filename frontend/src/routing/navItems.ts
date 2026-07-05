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
  FileText,
  KeyRound,
  LayoutDashboard,
  MessagesSquare,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { Permission } from "../auth/rbac";

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
}

/** The canonical navigation destinations, in display order. */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    id: "nav-dashboard",
    path: "/",
    label: "Dashboard",
    icon: LayoutDashboard,
    permission: "read",
  },
  {
    id: "nav-query",
    path: "/query",
    label: "Query",
    icon: Search,
    permission: "run_agents",
  },
  {
    id: "nav-documents",
    path: "/documents",
    label: "Documents",
    icon: FileText,
    permission: "read",
  },
  {
    id: "nav-agent",
    path: "/agents",
    label: "Agent Runs",
    icon: Bot,
    permission: "run_agents",
  },
  {
    id: "nav-multi-agent",
    path: "/multi-agent",
    label: "Multi-Agent",
    icon: Sparkles,
    permission: "run_agents",
  },
  {
    id: "nav-conversations",
    path: "/conversations",
    label: "Conversations",
    icon: MessagesSquare,
    permission: "read",
  },
  {
    id: "nav-prompts",
    path: "/prompts",
    label: "Prompts",
    icon: SlidersHorizontal,
    permission: "read",
  },
  {
    id: "nav-analytics",
    path: "/analytics",
    label: "Analytics",
    icon: BarChart3,
    permission: "read",
  },
  {
    id: "nav-guardrails",
    path: "/guardrails",
    label: "Guardrails",
    icon: ShieldCheck,
    permission: "read",
  },
  {
    id: "nav-evaluations",
    path: "/evaluations",
    label: "Evaluations",
    icon: ShieldCheck,
    permission: "read",
  },
  {
    id: "nav-members",
    path: "/members",
    label: "Members & Teams",
    icon: Users,
    permission: "manage_members",
  },
  {
    id: "nav-api-keys",
    path: "/api-keys",
    label: "API Keys",
    icon: KeyRound,
    permission: "manage_api_keys",
  },
];
