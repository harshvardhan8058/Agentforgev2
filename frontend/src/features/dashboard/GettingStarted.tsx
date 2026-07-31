/**
 * `GettingStarted`: a live activation checklist for the workspace.
 *
 * A fresh AgentForge install boots with an empty corpus and no usage, so most
 * surfaces legitimately render empty states — which makes it hard to tell what
 * to do next or which capabilities exist. This turns that into a guided path:
 * each step's completion is **derived from real API data** for the active
 * Org_Context (never from local flags), so it reflects the actual workspace and
 * stays correct across devices and sessions.
 *
 * Steps are RBAC-gated with the same `can(role, permission)` decision as the
 * sidebar, so a Role never sees a step it cannot complete. The two document /
 * usage queries reuse the exact cache keys `WorkspaceStats` uses, so mounting
 * both components issues no duplicate requests. Every query is independent and
 * fails soft: an errored signal is simply treated as "not yet done" rather than
 * blocking the dashboard.
 *
 * Once every applicable step is complete the checklist collapses to a single
 * confirmation row, so it stops competing for attention in a mature workspace.
 */
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import {
  ArrowRight,
  CheckCircle2,
  Circle,
  ClipboardCheck,
  FileText,
  KeyRound,
  Search,
  SlidersHorizontal,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { can, type Permission } from "../../auth/rbac";
import { useSession } from "../../auth/useSession";
import { Skeleton } from "../../components/ui/Skeleton";
import { cn } from "../../lib/cn";
import {
  apiKeysQuery,
  datasetsQuery,
  documentsQuery,
  promptsQuery,
  usageSummaryQuery,
} from "./workspaceQueries";

/** Treat a payload as a countable collection only when it really is one. */
function count(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

interface Step {
  id: string;
  label: string;
  description: string;
  to: string;
  cta: string;
  icon: LucideIcon;
  permission: Permission;
  done: boolean;
}

export function GettingStarted(): JSX.Element | null {
  const { orgId, role } = useSession();
  const canRead = role !== null && can(role, "read");
  const canManageKeys = role !== null && can(role, "manage_api_keys");

  // Canonical shared definitions — identical keys AND shapes to WorkspaceStats,
  // so mounting both issues one request per endpoint with no cache conflict.
  const documents = useQuery(documentsQuery(orgId, canRead));
  const usage = useQuery(usageSummaryQuery(orgId, canRead));
  const prompts = useQuery(promptsQuery(orgId, canRead));
  const datasets = useQuery(datasetsQuery(orgId, canRead));
  const apiKeys = useQuery(apiKeysQuery(orgId, canManageKeys));

  if (!canRead) return null;

  const allSteps: Step[] = [
    {
      id: "upload-document",
      label: "Upload a document",
      description: "Give AgentForge a corpus to ground its answers in.",
      to: "/documents",
      cta: "Upload",
      icon: FileText,
      permission: "ingest_documents",
      done: count(documents.data) > 0,
    },
    {
      id: "run-query",
      label: "Ask a grounded question",
      description: "Query your corpus and get an answer with citations.",
      to: "/query",
      cta: "Ask",
      icon: Search,
      permission: "run_agents",
      done: (usage.data?.total_tokens ?? 0) > 0,
    },
    {
      id: "run-multi-agent",
      label: "Run a multi-agent workflow",
      description: "Watch Planner → Researcher → Writer → Critic collaborate.",
      to: "/multi-agent",
      cta: "Launch",
      icon: Sparkles,
      permission: "run_agents",
      // The API exposes no run-list endpoint, so token usage is the only
      // read-only signal that any agent workflow has executed.
      done: (usage.data?.total_tokens ?? 0) > 0,
    },
    {
      id: "save-prompt",
      label: "Save a prompt template",
      description: "Version your prompts in the immutable registry.",
      to: "/prompts",
      cta: "Create",
      icon: SlidersHorizontal,
      permission: "ingest_documents",
      done: count(prompts.data) > 0,
    },
    {
      id: "create-dataset",
      label: "Create an evaluation dataset",
      description: "Score answer quality against curated examples.",
      to: "/evaluations",
      cta: "Create",
      icon: ClipboardCheck,
      permission: "run_agents",
      done: count(datasets.data) > 0,
    },
    {
      id: "issue-api-key",
      label: "Issue an API key",
      description: "Call AgentForge programmatically from your own code.",
      to: "/api-keys",
      cta: "Issue",
      icon: KeyRound,
      permission: "manage_api_keys",
      done: count(apiKeys.data) > 0,
    },
  ];

  const steps = allSteps.filter((s) => role !== null && can(role, s.permission));
  if (steps.length === 0) return null;

  const isLoading =
    documents.isLoading || usage.isLoading || prompts.isLoading || datasets.isLoading;

  if (isLoading) {
    return (
      <section aria-label="Getting started" data-testid="getting-started-loading">
        <Skeleton className="h-40 w-full" />
      </section>
    );
  }

  const completed = steps.filter((s) => s.done).length;
  const total = steps.length;
  const allDone = completed === total;

  // Mature workspace: collapse to a single, low-noise confirmation.
  if (allDone) {
    return (
      <section
        className="flex items-center gap-3 rounded-xl border border-border bg-surface px-5 py-4"
        aria-label="Getting started"
        data-testid="getting-started-complete"
      >
        <CheckCircle2 className="h-5 w-5 shrink-0 text-success" aria-hidden="true" />
        <p className="text-sm text-text-muted">
          <span className="font-medium text-text">Workspace fully set up.</span> You&apos;ve used
          every capability your role can reach.
        </p>
      </section>
    );
  }

  const pct = Math.round((completed / total) * 100);

  return (
    <section
      className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5 shadow-elevation-1"
      aria-labelledby="getting-started-heading"
      data-testid="getting-started"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-col gap-1">
          <h2
            id="getting-started-heading"
            className="text-sm font-semibold uppercase tracking-wide text-text-subtle"
          >
            Getting started
          </h2>
          <p className="text-sm text-text-muted">
            Work through these to exercise every part of the platform.
          </p>
        </div>
        <span
          className="text-sm font-medium text-text-muted"
          data-testid="getting-started-progress"
        >
          {completed} of {total} done
        </span>
      </div>

      {/* Progress bar — decorative; the text above is the accessible source. */}
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-bg-subtle"
        role="progressbar"
        aria-valuenow={completed}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-labelledby="getting-started-heading"
      >
        <div
          className="h-full rounded-full bg-gradient-brand transition-all duration-slow"
          style={{ width: `${pct}%` }}
        />
      </div>

      <ul className="flex flex-col gap-2">
        {steps.map((step) => {
          const Icon = step.icon;
          return (
            <li key={step.id}>
              <Link
                to={step.to}
                data-testid={`getting-started-step-${step.id}`}
                data-done={step.done}
                className={cn(
                  "group flex items-center gap-3 rounded-lg border border-border px-3 py-2.5",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg",
                  step.done ? "bg-bg-subtle" : "bg-surface hover:bg-surface-hover",
                )}
              >
                {step.done ? (
                  <CheckCircle2
                    className="h-5 w-5 shrink-0 text-success"
                    aria-hidden="true"
                  />
                ) : (
                  <Circle className="h-5 w-5 shrink-0 text-text-subtle" aria-hidden="true" />
                )}

                <Icon
                  className={cn(
                    "h-4 w-4 shrink-0",
                    step.done ? "text-text-subtle" : "text-primary",
                  )}
                  aria-hidden="true"
                />

                <span className="flex min-w-0 flex-col">
                  {/* Struck-through text conventionally means retracted or no
                      longer applicable, not accomplished. A completed step is
                      de-emphasised instead; its tick is the completion signal. */}
                  <span
                    className={cn(
                      "text-sm font-medium",
                      step.done ? "text-text-muted" : "text-text",
                    )}
                  >
                    {step.label}
                  </span>
                  {!step.done && (
                    <span className="text-xs text-text-muted">{step.description}</span>
                  )}
                </span>

                <span className="ml-auto flex shrink-0 items-center gap-1 text-xs font-medium text-text-subtle">
                  {step.done ? (
                    <span className="sr-only">Completed</span>
                  ) : (
                    <>
                      {step.cta}
                      <ArrowRight
                        className="h-3.5 w-3.5 transition-transform duration-fast group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    </>
                  )}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
