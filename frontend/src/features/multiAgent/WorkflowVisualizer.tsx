/**
 * `WorkflowVisualizer`: the animated Planner → Researcher → Writer → Critic
 * workflow (Req 10.2; Premium UX §3).
 *
 * Role nodes are styled with the per-role accent design tokens
 * (`role-planner`/`role-researcher`/`role-writer`/`role-critic`). As
 * `agent_started`/`plan`/`research`/`draft`/`critic_feedback` events arrive
 * (attributed by `role_id`, ordered by `sequence`), the active node is
 * highlighted and the per-role streaming panes fill with that role's events.
 *
 * Motion (node/edge transitions) is expressed through the `components/motion/`
 * primitives which are **reduced-motion aware** and collapse to an **instant,
 * static ordered layout** under `prefers-reduced-motion` (and under test) — no
 * information is ever hidden by the reduced-motion fallback.
 */
import { MotionFade } from "../../components/motion";
import { Badge } from "../../components/ui/Badge";
import { cn } from "../../lib/cn";
import type { SseFrame } from "../../api/sse/parse";
import type { MultiAgentStreamState } from "../../api/sse/multiAgentReducer";

interface RoleDef {
  id: string;
  label: string;
  /** Tailwind classes bound to the per-role accent token. */
  border: string;
  text: string;
  ring: string;
}

/** The canonical Planner → Researcher → Writer → Critic pipeline, in order. */
const ROLES: readonly RoleDef[] = [
  {
    id: "planner",
    label: "Planner",
    border: "border-role-planner",
    text: "text-role-planner",
    ring: "ring-role-planner",
  },
  {
    id: "researcher",
    label: "Researcher",
    border: "border-role-researcher",
    text: "text-role-researcher",
    ring: "ring-role-researcher",
  },
  {
    id: "writer",
    label: "Writer",
    border: "border-role-writer",
    text: "text-role-writer",
    ring: "ring-role-writer",
  },
  {
    id: "critic",
    label: "Critic",
    border: "border-role-critic",
    text: "text-role-critic",
    ring: "ring-role-critic",
  },
];

/** The `role_id` of the most recent event carrying one (the "active" role). */
function activeRoleId(state: MultiAgentStreamState): string | null {
  for (let i = state.events.length - 1; i >= 0; i--) {
    const roleId = state.events[i].data.role_id;
    if (typeof roleId === "string" && roleId.length > 0) return roleId;
  }
  return null;
}

/** A short, human-readable summary of one agent event's payload. */
function eventSummary(frame: SseFrame): string {
  const d = frame.data;
  if (typeof d.content === "string" && d.content.length > 0) return d.content;
  if (typeof d.comments === "string" && d.comments.length > 0) return d.comments;
  if (Array.isArray(d.steps) && d.steps.length > 0) {
    return d.steps.filter((s) => typeof s === "string").join(", ");
  }
  if (Array.isArray(d.findings) && d.findings.length > 0) {
    return `${d.findings.length} finding(s)`;
  }
  return frame.type;
}

export function WorkflowVisualizer({
  state,
}: {
  state: MultiAgentStreamState;
}): JSX.Element {
  const active = activeRoleId(state);

  return (
    <div className="flex flex-col gap-4" data-testid="workflow-visualizer">
      {/* Role node row — Planner → Researcher → Writer → Critic. */}
      <div
        className="flex flex-wrap items-center gap-2"
        data-testid="workflow-nodes"
        aria-label="Multi-agent workflow"
      >
        {ROLES.map((role, i) => {
          const isActive = active === role.id;
          const hasActivity = (state.byRole[role.id]?.length ?? 0) > 0;
          return (
            <div key={role.id} className="flex items-center gap-2">
              <MotionFade data-testid={`workflow-node-${role.id}`}>
                <div
                  data-active={isActive || undefined}
                  data-role={role.id}
                  className={cn(
                    "rounded-lg border bg-surface px-3 py-2 text-sm font-medium transition-colors",
                    hasActivity || isActive
                      ? cn(role.border, role.text)
                      : "border-border text-text-muted",
                    isActive && cn("ring-2 ring-offset-1 ring-offset-bg", role.ring),
                  )}
                >
                  {role.label}
                </div>
              </MotionFade>
              {i < ROLES.length - 1 && (
                <span
                  className="text-text-muted"
                  aria-hidden="true"
                  data-testid={`workflow-edge-${role.id}`}
                >
                  →
                </span>
              )}
            </div>
          );
        })}
      </div>

      {/* Per-role streaming panes, attributing events by role_id. */}
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-4">
        {ROLES.map((role) => {
          const events = state.byRole[role.id] ?? [];
          if (events.length === 0) return null;
          return (
            <div
              key={role.id}
              data-testid={`role-pane-${role.id}`}
              className={cn(
                "flex flex-col gap-2 rounded-lg border bg-surface p-3",
                role.border,
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className={cn("text-sm font-semibold", role.text)}>
                  {role.label}
                </span>
                <Badge tone="neutral">{events.length}</Badge>
              </div>
              <ul className="flex flex-col gap-1.5">
                {events.map((e, i) => (
                  <li
                    key={`${role.id}-${i}`}
                    data-testid={`role-event-${role.id}-${i}`}
                    className="text-xs text-text-muted"
                  >
                    <span className="font-mono text-text">{e.type}</span>
                    {": "}
                    {eventSummary(e)}
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </div>
  );
}
