/**
 * The command registry for the ⌘K palette.
 *
 * `buildCommands` is a pure function of a set of handlers: it produces the full
 * command list (navigation destinations + actions), each tagged with the
 * `Permission` it requires. The palette itself applies the RBAC gate
 * (`can(role, permission)`) so an action the Session Role cannot perform is
 * never surfaced (Req 4.2–4.5) — mirroring the sidebar nav gate exactly.
 */
import {
  MessageSquarePlus,
  Moon,
  PlayCircle,
  Building2,
  Keyboard,
  Search,
  Sparkles,
  UploadCloud,
  type LucideIcon,
} from "lucide-react";

import type { Permission } from "../../auth/rbac";
import { NAV_ITEMS } from "../../routing/navItems";

/** A single palette command. */
export interface Command {
  id: string;
  label: string;
  /** Overlay/palette group heading. */
  group: string;
  /** Extra search terms for cmdk fuzzy matching. */
  keywords?: string[];
  /** Permission required to surface the command (`null` = any session). */
  permission: Permission | null;
  icon?: LucideIcon;
  /** The effect of choosing the command. */
  perform(): void;
}

/** Handlers the palette wires into the built commands. */
export interface CommandHandlers {
  navigate(path: string): void;
  toggleTheme(): void;
  openShortcuts(): void;
  switchOrg(): void;
}

/**
 * Build the full command list (pure). Navigation commands mirror `NAV_ITEMS`
 * and inherit their permission; action commands declare their own.
 */
export function buildCommands(handlers: CommandHandlers): Command[] {
  const navCommands: Command[] = NAV_ITEMS.map((item) => ({
    id: `cmd-${item.id}`,
    label: `Go to ${item.label}`,
    group: "Navigation",
    keywords: [item.label, item.path],
    permission: item.permission,
    icon: item.icon,
    perform: () => handlers.navigate(item.path),
  }));

  const actionCommands: Command[] = [
    {
      id: "cmd-new-query",
      label: "New query",
      group: "Actions",
      keywords: ["ask", "search", "rag"],
      permission: "run_agents",
      icon: Search,
      perform: () => handlers.navigate("/query"),
    },
    {
      id: "cmd-start-run",
      label: "Start agent run",
      group: "Actions",
      keywords: ["run", "agent", "execute"],
      permission: "run_agents",
      icon: PlayCircle,
      perform: () => handlers.navigate("/agents"),
    },
    {
      id: "cmd-multi-agent-run",
      label: "Start multi-agent run",
      group: "Actions",
      keywords: ["multi", "planner", "researcher", "writer", "critic", "workflow"],
      permission: "run_agents",
      icon: Sparkles,
      perform: () => handlers.navigate("/multi-agent"),
    },
    {
      id: "cmd-upload-document",
      label: "Upload a document",
      group: "Actions",
      keywords: ["upload", "document", "ingest", "corpus", "file"],
      permission: "ingest_documents",
      icon: UploadCloud,
      perform: () => handlers.navigate("/documents"),
    },
    {
      id: "cmd-new-conversation",
      label: "New conversation",
      group: "Actions",
      keywords: ["chat", "thread"],
      permission: "run_agents",
      icon: MessageSquarePlus,
      perform: () => handlers.navigate("/conversations"),
    },
    {
      id: "cmd-switch-org",
      label: "Switch organization",
      group: "Actions",
      keywords: ["org", "tenant", "workspace"],
      permission: "read",
      icon: Building2,
      perform: () => handlers.switchOrg(),
    },
    {
      id: "cmd-toggle-theme",
      label: "Toggle theme",
      group: "Actions",
      keywords: ["dark", "light", "appearance"],
      permission: null,
      icon: Moon,
      perform: () => handlers.toggleTheme(),
    },
    {
      id: "cmd-open-shortcuts",
      label: "Open keyboard shortcuts",
      group: "Actions",
      keywords: ["help", "keys", "?"],
      permission: null,
      icon: Keyboard,
      perform: () => handlers.openShortcuts(),
    },
  ];

  return [...navCommands, ...actionCommands];
}
