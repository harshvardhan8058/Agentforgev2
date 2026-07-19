/**
 * `PageHeader`: the consistent title block used at the top of every feature
 * view.
 *
 * Establishes a single, uniform information hierarchy across the app — an
 * optional eyebrow label, the page title (`<h1>`), a supporting description,
 * and a right-aligned actions slot that wraps gracefully on small screens. An
 * optional leading icon renders inside a tinted brand token badge.
 *
 * Presentational only. It never fetches, gates, or mutates — callers own that.
 */
import { type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "../../lib/cn";

export function PageHeader({
  title,
  description,
  eyebrow,
  icon: Icon,
  actions,
  className,
  "data-testid": testId,
}: {
  title: string;
  description?: ReactNode;
  eyebrow?: string;
  icon?: LucideIcon;
  actions?: ReactNode;
  className?: string;
  "data-testid"?: string;
}): JSX.Element {
  return (
    <header
      data-testid={testId}
      className={cn(
        "flex flex-col gap-4 border-b border-border pb-5 sm:flex-row sm:items-start sm:justify-between",
        className,
      )}
    >
      <div className="flex min-w-0 items-start gap-3.5">
        {Icon && (
          <span
            aria-hidden="true"
            className="mt-0.5 hidden h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-primary sm:inline-flex"
          >
            <Icon className="h-5 w-5" />
          </span>
        )}
        <div className="flex min-w-0 flex-col gap-1">
          {eyebrow && (
            <span className="text-xs font-semibold uppercase tracking-wide text-text-subtle">
              {eyebrow}
            </span>
          )}
          <h1 className="truncate text-2xl font-semibold tracking-tight text-text">
            {title}
          </h1>
          {description && (
            <p className="max-w-2xl text-sm text-text-muted">{description}</p>
          )}
        </div>
      </div>
      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>
      )}
    </header>
  );
}
