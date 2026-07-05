/**
 * `EmptyState`: explicit empty-state rendering for zero-result views (Req 6.2,
 * 11.5, 13.5). A later task restyles it via the design system; the markup here
 * is semantic and accessible.
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
      className="empty-state flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border bg-bg-subtle p-10 text-center"
      data-testid="empty-state"
    >
      <div className="text-text-muted" aria-hidden="true">
        {icon ?? <Inbox className="h-8 w-8" />}
      </div>
      <h2 className="empty-state__title text-lg font-semibold text-text">{title}</h2>
      {message && (
        <p className="empty-state__message max-w-sm text-sm text-text-muted">
          {message}
        </p>
      )}
      {action && <div className="empty-state__action mt-1">{action}</div>}
    </div>
  );
}
