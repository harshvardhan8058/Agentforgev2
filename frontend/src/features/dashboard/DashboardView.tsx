/**
 * `DashboardView`: the authenticated landing surface (`/`).
 *
 * A workspace home rendered inside the RBAC-aware `AppShell`. It orients the
 * Operator with their active Org_Context + Role, offers permission-gated
 * quick actions into the primary workflows, and surfaces the platform
 * capabilities they can reach — every destination gated by the same
 * `can(role, permission)` decision used by the sidebar and command palette, so
 * nothing unreachable is ever shown.
 *
 * The layout itself is presentational; the two data-backed sections it composes
 * (`WorkspaceStats` and `GettingStarted`) fetch their own signals through the
 * shared definitions in `workspaceQueries`, so they never fabricate a metric and
 * never issue duplicate requests for the same endpoint.
 */
import type { JSX } from "react";
import { Link } from "react-router";
import {
  ArrowRight,
  Bot,
  FileText,
  Search,
  Sparkles,
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
import { CopyableId } from "../../components/ui/CopyableId";
import { Kbd } from "../../components/ui/Kbd";
import { WorkspaceStats } from "./WorkspaceStats";
import { GettingStarted } from "./GettingStarted";

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
            {/* The id is needed for API calls and support requests, but a full
                UUID printed in the header spent a line on something unreadable
                and unselectable. Shortened, with the full value on the copy
                button. */}
            {orgId && orgLabel(orgId) !== orgId && (
              <CopyableId
                value={orgId}
                label="organization id"
                testId="workspace-org-id"
              />
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

      {/* Live workspace metrics. */}
      <WorkspaceStats />

      {/* Guided activation path, derived from real workspace data. */}
      <GettingStarted />

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

      {/*
        An "Explore" grid used to follow, holding a card for every remaining
        destination: Conversations, Prompts, Analytics, Guardrails, Evaluations,
        Members and API Keys. All seven are permanent entries in the sidebar two
        pixels to the left, so the section restated the navigation as eleven
        near-identical cards and pushed the workspace's actual state — documents,
        tokens, cost, the checklist — off the first screen. Quick actions are kept
        because they are task-framed entry points rather than a copy of the nav;
        everything else is reachable from the sidebar or ⌘K.
      */}

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
