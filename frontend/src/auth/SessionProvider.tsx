/**
 * SessionProvider: owns the Session state and keeps it in sync with the shared
 * token store.
 *
 * On mount it hydrates the token from storage, decodes its claims via
 * `decodeClaims`, and validates expiry via `isExpired`. It subscribes to the
 * token store so a token replaced/cleared by the API_Client auth middleware
 * (401 refresh / terminal 401) immediately re-derives the Session. `login`
 * stores a token; `logout` clears the token and all derived state (Req 3.1,
 * 3.2, 3.4).
 */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { decodeClaims, isExpired } from "./token";
import {
  clearToken,
  getToken,
  setToken,
  subscribe,
} from "./tokenStore";
import { SessionContext, type SessionApi } from "./useSession";

/** Current wall-clock time in whole seconds since the epoch. */
function nowSeconds(): number {
  return Math.floor(Date.now() / 1000);
}

export function SessionProvider({ children }: { children: ReactNode }): JSX.Element {
  const [token, setTokenState] = useState<string | null>(() => getToken());

  // Keep local state in lockstep with the shared token store.
  useEffect(() => subscribe(setTokenState), []);

  const claims = useMemo(() => (token ? decodeClaims(token) : null), [token]);

  // A session is valid iff its claims decode AND it is not expired (Req 3.2).
  const valid = claims !== null && !isExpired(claims, nowSeconds());
  const effectiveClaims = valid ? claims : null;

  const login = useCallback((next: string) => setToken(next), []);
  const logout = useCallback(() => clearToken(), []);

  const value = useMemo<SessionApi>(
    () => ({
      token,
      claims: effectiveClaims,
      orgId: effectiveClaims?.org_id ?? null,
      role: effectiveClaims?.role ?? null,
      isAuthenticated: valid,
      login,
      logout,
    }),
    [token, effectiveClaims, valid, login, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}
