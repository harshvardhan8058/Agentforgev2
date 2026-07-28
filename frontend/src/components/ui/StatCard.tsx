/**
 * `StatCard`: a compact metric tile for dashboards and analytics.
 *
 * Renders a labeled value with an optional leading icon and a supporting hint
 * line. Values are rendered verbatim (no formatting) so metric-precision
 * guarantees elsewhere are never altered by the presentation layer. The icon
 * badge uses the tinted brand token by default and accepts a semantic tone.
 */
import type { JSX } from "react";
import { type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "../../lib/cn";

export type StatTone = "primary" | "success" | "warning" | "danger" | "info";

const TONE_BADGE: Record<StatTone, string> = {
  primary: "bg-primary-subtle text-primary",
  success: "bg-success/15 text-success",
  warning: "bg-warning/15 text-warning",
  danger: "bg-danger/15 text-danger",
  info: "bg-info/15 text-info",
};

export function StatCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = "primary",
  className,
  "data-testid": testId,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  icon?: LucideIcon;
  tone?: StatTone;
  className?: string;
  "data-testid"?: string;
}): JSX.Element {
  return (
    <div
      data-testid={testId}
      className={cn(
        "flex items-start justify-between gap-3 rounded-lg border border-border bg-surface bg-gradient-surface p-5 shadow-elevation-1",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col gap-1.5">
        <span className="text-xs font-medium uppercase tracking-wide text-text-subtle">
          {label}
        </span>
        <span className="text-2xl font-semibold tracking-tight text-text">
          {value}
        </span>
        {hint && <span className="text-xs text-text-muted">{hint}</span>}
      </div>
      {Icon && (
        <span
          aria-hidden="true"
          className={cn(
            "inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
            TONE_BADGE[tone],
          )}
        >
          <Icon className="h-5 w-5" />
        </span>
      )}
    </div>
  );
}
