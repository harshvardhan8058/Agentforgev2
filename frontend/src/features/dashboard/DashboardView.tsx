/**
 * `DashboardView`: the authenticated landing surface (`/`).
 *
 * A lightweight welcome/home rendered inside the RBAC-aware `AppShell` (which
 * already provides the persistent `OrgContextBadge`, org switcher, RBAC nav, and
 * logout — Req 4.1). Feature-rich dashboards arrive in later tasks; this keeps
 * the protected home meaningful while the auth/org/management surfaces land.
 */
import { useSession } from "../../auth/useSession";

export function DashboardView(): JSX.Element {
  const { orgId, role } = useSession();
  return (
    <div className="flex flex-col gap-4" data-testid="home-view">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight text-text">Dashboard</h1>
        <p className="text-sm text-text-muted">
          Welcome to your AgentForge workspace.
        </p>
      </header>
      <p className="text-sm text-text-muted">
        Operating in{" "}
        <span className="font-medium text-text">{orgId ?? "—"}</span> as{" "}
        <span className="font-medium capitalize text-text">{role ?? "—"}</span>.
      </p>
    </div>
  );
}
