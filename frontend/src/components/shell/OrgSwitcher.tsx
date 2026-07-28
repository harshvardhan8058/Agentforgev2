/**
 * `OrgSwitcher`: switch the active Org_Context by adopting the stored token
 * whose `org_id` matches the selection (Req 4.6).
 *
 * Lists every organization the Operator holds a decodable token for (via
 * `orgTokenStore`) and, on selection, calls `session.login(token)` with the
 * matching-`org_id` token — re-deriving the Session (and re-scoping server
 * queries) under the new context. Listens for the ⌘K "switch organization"
 * command to open programmatically.
 */
import type { JSX } from "react";
import { useEffect, useState } from "react";
import { Building2, Check, ChevronsUpDown } from "lucide-react";

import { useSession } from "../../auth/useSession";
import {
  listKnownOrgs,
  rememberOrgToken,
  tokenForOrg,
  type KnownOrg,
} from "../../auth/orgTokenStore";
import { OPEN_ORG_SWITCHER_EVENT } from "../../hooks/useCommandPalette";
import { orgLabel } from "../../auth/orgNameStore";
import { orgMonogram, orgMonogramStyle } from "../../lib/orgIdentity";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/DropdownMenu";

export function OrgSwitcher(): JSX.Element | null {
  const { token, orgId, login } = useSession();
  const [open, setOpen] = useState(false);
  const [orgs, setOrgs] = useState<KnownOrg[]>([]);

  // Remember the current token so at least the active org is switchable, then
  // read the full set of known orgs.
  useEffect(() => {
    if (token) rememberOrgToken(token);
    setOrgs(listKnownOrgs());
  }, [token]);

  // The ⌘K "Switch organization" command opens this menu.
  useEffect(() => {
    const onOpen = (): void => {
      setOrgs(listKnownOrgs());
      setOpen(true);
    };
    window.addEventListener(OPEN_ORG_SWITCHER_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_ORG_SWITCHER_EVENT, onOpen);
  }, []);

  if (orgId === null) return null;

  function selectOrg(nextOrgId: string): void {
    const nextToken = tokenForOrg(nextOrgId);
    if (nextToken) {
      login(nextToken);
    }
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      {/* Compact icon-only control: the active org identity + role already live
          in the OrgContextBadge, so the switcher is just a monogram + chevron to
          avoid a duplicated identifier chip in the top bar. */}
      <DropdownMenuTrigger
        data-testid="org-switcher-trigger"
        aria-label="Switch organization"
        title={`Switch organization (current: ${orgLabel(orgId)})`}
        className="inline-flex items-center gap-1 rounded-md border border-border bg-surface px-1.5 py-1.5 text-sm text-text transition-colors hover:border-border-strong hover:bg-surface-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
      >
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[0.65rem] font-semibold"
          style={orgMonogramStyle(orgId)}
          aria-hidden="true"
        >
          {orgMonogram(orgId)}
        </span>
        <span className="sr-only" data-testid="org-switcher-current">
          {orgLabel(orgId)}
        </span>
        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" data-testid="org-switcher-menu" className="min-w-[15rem]">
        <div className="flex items-center gap-2 px-2 pb-1.5 pt-1 text-xs font-medium uppercase tracking-wide text-text-subtle">
          <Building2 className="h-3.5 w-3.5" aria-hidden="true" />
          Organizations
        </div>
        {orgs.map((org) => (
          <DropdownMenuItem
            key={org.orgId}
            data-testid={`org-option-${org.orgId}`}
            onSelect={() => selectOrg(org.orgId)}
          >
            <span
              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[0.65rem] font-semibold"
              style={orgMonogramStyle(org.orgId)}
              aria-hidden="true"
            >
              {orgMonogram(org.orgId)}
            </span>
            <span className="min-w-0 flex-1 truncate" title={org.orgId}>
              {orgLabel(org.orgId)}
            </span>
            <span className="shrink-0 text-xs capitalize text-text-muted">{org.role}</span>
            <Check
              className={org.orgId === orgId ? "h-4 w-4 shrink-0 text-primary" : "h-4 w-4 shrink-0 opacity-0"}
              aria-hidden="true"
            />
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
