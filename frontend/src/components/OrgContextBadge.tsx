/**
 * `OrgContextBadge`: the persistent Org_Context + Role display (Req 4.1).
 *
 * Renders the active organization and role derived from the current
 * Access_Token as a compact workspace chip: a deterministic org monogram, the
 * org identifier (visually truncated, full value on hover via `title`), and the
 * role. When unauthenticated it renders nothing (the badge only appears within
 * the authenticated layout).
 */
import type { JSX } from "react";
import { useSession } from "../auth/useSession";
import { orgLabel } from "../auth/orgNameStore";
import { orgMonogram, orgMonogramStyle } from "../lib/orgIdentity";

export function OrgContextBadge(): JSX.Element | null {
  const { orgId, role, isAuthenticated } = useSession();
  if (!isAuthenticated || orgId === null || role === null) {
    return null;
  }
  return (
    <div
      className="org-context-badge inline-flex max-w-[15rem] items-center gap-2 rounded-full border border-border bg-surface-raised py-1 pl-1 pr-2.5 text-xs"
      data-testid="org-context-badge"
      aria-label="Active organization and role"
    >
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[0.65rem] font-semibold"
        style={orgMonogramStyle(orgId)}
        aria-hidden="true"
      >
        {orgMonogram(orgId)}
      </span>
      <span
        className="org-context-badge__org min-w-0 truncate font-medium text-text"
        data-testid="org-context-org"
        title={orgId}
      >
        {orgLabel(orgId)}
      </span>
      <span
        className="org-context-badge__role shrink-0 rounded-full bg-primary-subtle px-2 py-0.5 font-medium capitalize text-primary"
        data-testid="org-context-role"
      >
        {role}
      </span>
    </div>
  );
}
