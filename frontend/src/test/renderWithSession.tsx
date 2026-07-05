/**
 * Test helper: render a subtree under a crafted Session context, without
 * needing a real token. Lets component tests exercise RBAC-gated rendering for
 * a specific Role directly.
 */
import { type ReactNode } from "react";
import { render, type RenderResult } from "@testing-library/react";

import { SessionContext, type SessionApi } from "../auth/useSession";
import type { Role } from "../auth/token";

export function makeSession(role: Role | null): SessionApi {
  const authenticated = role !== null;
  return {
    token: authenticated ? "test-token" : null,
    claims: authenticated
      ? { sub: "u1", org_id: "org-1", role: role!, exp: 9_999_999_999 }
      : null,
    orgId: authenticated ? "org-1" : null,
    role,
    isAuthenticated: authenticated,
    login: () => {},
    logout: () => {},
  };
}

export function renderWithSession(
  ui: ReactNode,
  session: SessionApi,
): RenderResult {
  return render(
    <SessionContext.Provider value={session}>{ui}</SessionContext.Provider>,
  );
}
