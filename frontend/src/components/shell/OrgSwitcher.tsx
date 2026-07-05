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
      <DropdownMenuTrigger
        data-testid="org-switcher-trigger"
        aria-label="Switch organization"
        className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-text hover:border-border-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring"
      >
        <Building2 className="h-4 w-4 text-text-muted" aria-hidden="true" />
        <span className="max-w-[10rem] truncate" data-testid="org-switcher-current">
          {orgId}
        </span>
        <ChevronsUpDown className="h-3.5 w-3.5 text-text-muted" aria-hidden="true" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" data-testid="org-switcher-menu">
        {orgs.map((org) => (
          <DropdownMenuItem
            key={org.orgId}
            data-testid={`org-option-${org.orgId}`}
            onSelect={() => selectOrg(org.orgId)}
          >
            <Check
              className={org.orgId === orgId ? "h-4 w-4 text-primary" : "h-4 w-4 opacity-0"}
              aria-hidden="true"
            />
            <span className="truncate">{org.orgId}</span>
            <span className="ml-auto text-xs capitalize text-text-muted">{org.role}</span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
