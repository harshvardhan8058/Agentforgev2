/**
 * `useSession` + the Session context type.
 *
 * The Session is the Web_Client's in-memory representation of an authenticated
 * Operator, derived from the stored Access_Token and its decoded claims.
 */
import { createContext, useContext } from "react";

import type { Claims, Role } from "./token";

/** The Session API exposed to components (Req 3.1, 3.4, 4.1). */
export interface SessionApi {
  /** The raw stored Access_Token, or `null`. */
  token: string | null;
  /** Decoded claims, or `null` when unauthenticated/expired. */
  claims: Claims | null;
  orgId: string | null;
  role: Role | null;
  /** True iff a token is present AND not expired. */
  isAuthenticated: boolean;
  /** Store a token for the Session (login/register/org-switch). */
  login(token: string): void;
  /** Clear the token + all derived Session state (Req 3.4). */
  logout(): void;
}

export const SessionContext = createContext<SessionApi | null>(null);

/** Access the current Session. Must be used within a `SessionProvider`. */
export function useSession(): SessionApi {
  const ctx = useContext(SessionContext);
  if (ctx === null) {
    throw new Error("useSession must be used within a SessionProvider");
  }
  return ctx;
}
