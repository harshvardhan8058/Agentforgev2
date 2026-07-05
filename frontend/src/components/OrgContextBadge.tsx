/**
 * `OrgContextBadge`: the persistent Org_Context + Role display (Req 4.1).
 *
 * Renders the active organization and role derived from the current
 * Access_Token. When unauthenticated it renders nothing (the badge only
 * appears within the authenticated layout).
 */
import { useSession } from "../auth/useSession";

export function OrgContextBadge(): JSX.Element | null {
  const { orgId, role, isAuthenticated } = useSession();
  if (!isAuthenticated || orgId === null || role === null) {
    return null;
  }
  return (
    <div
      className="org-context-badge inline-flex items-center gap-2 rounded-full border border-border bg-surface-raised px-3 py-1 text-xs"
      data-testid="org-context-badge"
      aria-label="Active organization and role"
    >
      <span
        className="org-context-badge__org font-medium text-text"
        data-testid="org-context-org"
      >
        {orgId}
      </span>
      <span
        className="org-context-badge__role rounded-full bg-primary/15 px-2 py-0.5 font-medium capitalize text-primary"
        data-testid="org-context-role"
      >
        {role}
      </span>
    </div>
  );
}
