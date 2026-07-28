/**
 * `Can`: the RBAC gate (Property 3).
 *
 * Renders its children **iff** the Session Role grants the required Permission
 * per the backend role→permission map; otherwise it renders nothing, so an
 * unauthorized control is **absent from the DOM** (not merely disabled) — the
 * client can never expose an action the backend would not authorize (Req
 * 4.2–4.5).
 */
import type { JSX } from "react";
import { type ReactNode } from "react";

import { can, type Permission } from "../auth/rbac";
import { useSession } from "../auth/useSession";

export function Can({
  permission,
  children,
}: {
  permission: Permission;
  children: ReactNode;
}): JSX.Element | null {
  const { role } = useSession();
  if (role === null || !can(role, permission)) {
    return null;
  }
  return <>{children}</>;
}
