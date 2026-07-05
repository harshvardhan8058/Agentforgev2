/**
 * `EmptyState`: explicit empty-state rendering for zero-result views (Req 6.2,
 * 11.5, 13.5). A later task restyles it via the design system; the markup here
 * is semantic and accessible.
 */
import { type ReactNode } from "react";

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message?: string;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="empty-state" data-testid="empty-state">
      <h2 className="empty-state__title">{title}</h2>
      {message && <p className="empty-state__message">{message}</p>}
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  );
}
