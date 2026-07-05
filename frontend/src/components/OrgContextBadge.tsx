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
    <div className="org-context-badge" data-testid="org-context-badge" aria-label="Active organization and role">
      <span className="org-context-badge__org" data-testid="org-context-org">
        {orgId}
      </span>
      <span className="org-context-badge__role" data-testid="org-context-role">
        {role}
      </span>
    </div>
  );
}
