/**
 * `EmptyState`: explicit empty-state rendering for zero-result views (Req 6.2,
 * 11.5, 13.5).
 *
 * A premium, centered zero-state: a tinted brand icon medallion, a clear title,
 * supporting copy, and an optional primary action. Semantic and accessible —
 * the icon is decorative and the title reads as a heading.
 */
import { type ReactNode } from "react";
import { Inbox } from "lucide-react";

export function EmptyState({
  title,
  message,
  action,
  icon,
}: {
  title: string;
  message?: string;
  action?: ReactNode;
  icon?: ReactNode;
}): JSX.Element {
  return (
    <div
      className="empty-state flex flex-col items-center justify-center gap-4 rounded-xl border border-dashed border-border bg-bg-subtle bg-gradient-surface px-6 py-14 text-center"
      data-testid="empty-state"
    >
      <div
        className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary-subtle text-primary"
        aria-hidden="true"
      >
        {icon ?? <Inbox className="h-7 w-7" />}
      </div>
      <div className="flex flex-col gap-1.5">
        <h2 className="empty-state__title text-lg font-semibold tracking-tight text-text">
          {title}
        </h2>
        {message && (
          <p className="empty-state__message mx-auto max-w-sm text-sm text-text-muted">
            {message}
          </p>
        )}
      </div>
      {action && <div className="empty-state__action mt-1">{action}</div>}
    </div>
  );
}
