/**
 * `DashboardView`: the authenticated landing surface (`/`).
 *
 * A workspace home rendered inside the RBAC-aware `AppShell`. It orients the
 * Operator with their active Org_Context + Role, offers permission-gated
 * quick actions into the primary workflows, and surfaces the platform
 * capabilities they can reach — every destination gated by the same
 * `can(role, permission)` decision used by the sidebar and command palette, so
 * nothing unreachable is ever shown. Presentational only; it makes no network
 * calls and fabricates no metrics.
 */
import { Link } from "react-router-dom";
import {
  ArrowRight,
  BarChart3,
  Bot,
  ClipboardCheck,
  FileText,
  KeyRound,
  MessagesSquare,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Users,
  type LucideIcon,
} from "lucide-react";

import { can, type Permission } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { orgLabel } from "../../auth/orgNameStore";
import { useCommandPalette } from "../../hooks/useCommandPalette";
import { orgMonogram, orgMonogramStyle } from "../../lib/orgIdentity";
import { cn } from "../../lib/cn";
import { PageHeader } from "../../components/ui/PageHeader";
import { Badge } from "../../components/ui/Badge";
import { Kbd } from "../../components/ui/Kbd";

interface Destination {
  label: string;
  description: string;
  to: string;
  icon: LucideIcon;
  permission: Permission | null;
}

const QUICK_ACTIONS: readonly Destination[] = [
  {
    label: "Ask a question",
    description: "Run a grounded RAG query and get a cited answer.",
    to: "/query",
    icon: Search,
    permission: "run_agents",
  },
  {
    label: "Upload documents",
    description: "Ingest and manage your organization's corpus.",
    to: "/documents",
    icon: FileText,
    permission: "read",
  },
  {
    label: "Run an agent",
    description: "Execute a single-agent run and stream its trace.",
    to: "/agents",
    icon: Bot,
    permission: "run_agents",
  },
  {
    label: "Multi-agent workflow",
    description: "Launch a Planner → Researcher → Writer → Critic run.",
    to: "/multi-agent",
    icon: Sparkles,
    permission: "run_agents",
  },
];

const CAPABILITIES: readonly Destination[] = [
  {
    label: "Conversations",
    description: "Continue threaded, context-aware sessions.",
    to: "/conversations",
    icon: MessagesSquare,
    permission: "read",
  },
  {
    label: "Prompts",
    description: "Browse and diff the immutable prompt registry.",
    to: "/prompts",
    icon: SlidersHorizontal,
    permission: "read",
  },
  {
    label: "Analytics",
    description: "Track token usage and cost across providers.",
    to: "/analytics",
    icon: BarChart3,
    permission: "read",
  },
  {
    label: "Guardrails",
    description: "Review the policies applied to every answer.",
    to: "/guardrails",
    icon: ShieldCheck,
    permission: "read",
  },
  {
    label: "Evaluations",
    description: "Measure quality against curated datasets.",
    to: "/evaluations",
    icon: ClipboardCheck,
    permission: "read",
  },
  {
    label: "Members & Teams",
    description: "Manage who can access this organization.",
    to: "/members",
    icon: Users,
    permission: "manage_members",
  },
  {
    label: "API Keys",
    description: "Issue and revoke programmatic access keys.",
    to: "/api-keys",
    icon: KeyRound,
    permission: "manage_api_keys",
  },
];

function DestinationCard({
  item,
  featured = false,
}: {
  item: Destination;
  featured?: boolean;
}): JSX.Element {
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      data-testid={`dashboard-action-${item.to.replace(/\//g, "") || "home"}`}
      className={cn(
        "af-interactive group flex flex-col gap-3 rounded-lg border border-border bg-surface bg-gradient-surface p-5 shadow-elevation-1",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
      )}
    >
      <div className="flex items-center justify-between">
        <span
          className={cn(
            "inline-flex h-10 w-10 items-center justify-center rounded-lg",
            featured ? "bg-gradient-brand text-white" : "bg-primary-subtle text-primary",
          )}
          aria-hidden="true"
        >
          <Icon className="h-5 w-5" />
        </span>
        <ArrowRight
          className="h-4 w-4 text-text-subtle transition-transform duration-fast group-hover:translate-x-0.5 group-hover:text-text-muted"
          aria-hidden="true"
        />
      </div>
      <div className="flex flex-col gap-1">
        <span className="font-semibold tracking-tight text-text">{item.label}</span>
        <span className="text-sm text-text-muted">{item.description}</span>
      </div>
    </Link>
  );
}

export function DashboardView(): JSX.Element {
  const { orgId, role } = useSession();
  const { openPalette } = useCommandPalette();

  const permitted = (item: Destination): boolean =>
    item.permission === null || (role !== null && can(role, item.permission));

  const quickActions = QUICK_ACTIONS.filter(permitted);
  const capabilities = CAPABILITIES.filter(permitted);

  return (
    <div className="flex flex-col gap-8" data-testid="home-view">
      <PageHeader
        eyebrow="Workspace"
        title="Dashboard"
        description="Welcome to your AgentForge workspace. Jump into a workflow or explore what your role can access."
      />

      {/* Workspace identity band. */}
      <section
        className="flex flex-col gap-4 overflow-hidden rounded-xl border border-border bg-gradient-brand-soft p-6 sm:flex-row sm:items-center sm:justify-between"
        data-testid="workspace-identity"
      >
        <div className="flex items-center gap-4">
          {orgId && (
            <span
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-lg font-semibold"
              style={orgMonogramStyle(orgId)}
              aria-hidden="true"
            >
              {orgMonogram(orgId)}
            </span>
          )}
          <div className="flex min-w-0 flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-wide text-text-subtle">
              Active organization
            </span>
            <span
              className="truncate text-lg font-semibold tracking-tight text-text"
              data-testid="workspace-org-label"
              title={orgId ?? undefined}
            >
              {orgId ? orgLabel(orgId) : "—"}
            </span>
            {orgId && orgLabel(orgId) !== orgId && (
              <span
                className="truncate font-mono text-xs text-text-subtle"
                data-testid="workspace-org-id"
                title={orgId}
              >
                {orgId}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-sm text-text-muted">Signed in as</span>
          <Badge tone="primary" className="capitalize">
            {role ?? "—"}
          </Badge>
        </div>
      </section>

      {/* Quick actions. */}
      {quickActions.length > 0 && (
        <section className="flex flex-col gap-3" aria-labelledby="quick-actions-heading">
          <h2
            id="quick-actions-heading"
            className="text-sm font-semibold uppercase tracking-wide text-text-subtle"
          >
            Quick actions
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {quickActions.map((item, index) => (
              <DestinationCard key={item.to} item={item} featured={index === 0} />
            ))}
          </div>
        </section>
      )}

      {/* Capability grid. */}
      {capabilities.length > 0 && (
        <section className="flex flex-col gap-3" aria-labelledby="explore-heading">
          <h2
            id="explore-heading"
            className="text-sm font-semibold uppercase tracking-wide text-text-subtle"
          >
            Explore
          </h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {capabilities.map((item) => (
              <DestinationCard key={item.to} item={item} />
            ))}
          </div>
        </section>
      )}

      {/* Keyboard hint. */}
      <p className="flex flex-wrap items-center gap-2 text-sm text-text-muted">
        Tip: press
        <button
          type="button"
          onClick={openPalette}
          className="inline-flex items-center rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
          aria-label="Open the command palette"
        >
          <Kbd>⌘K</Kbd>
        </button>
        to jump anywhere or run an action.
      </p>
    </div>
  );
}
