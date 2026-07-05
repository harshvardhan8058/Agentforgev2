/**
 * The single typed API_Client instance.
 *
 * Every Backend_API call flows through this module (Req 1.2). It is a single
 * `openapi-fetch` client bound to `config.baseUrl` and typed by the generated
 * `schema.d.ts`, so the client surface is exactly the shipped OpenAPI contract:
 * the client cannot reference an endpoint or field the backend does not define,
 * and any UI capability lacking a shipped contract is simply not expressible
 * here (Req 1.3, 1.6).
 *
 * The auth middleware is attached here: request-side bearer attach and
 * response-side 401 refresh-once-then-retry (Req 2.6, 3.3, 3.5, 3.6). No secret
 * is embedded; only the base URL from `import.meta.env` is used (Req 1.5).
 */
import createClient from "openapi-fetch";

import { config } from "../config";
import type { paths } from "./schema";
import {
  createAuthMiddleware,
  type AuthMiddlewareDeps,
} from "./auth-middleware";
import {
  getToken,
  setToken,
  handleUnauthenticated,
} from "../auth/tokenStore";

/** The typed API_Client. All feature code imports this single instance. */
export const apiClient = createClient<paths>({
  baseUrl: config.baseUrl,
  // Defer to the live global `fetch` at call time (rather than capturing a
  // reference at construction). Behaviorally identical in the browser and keeps
  // the transport interceptable by test tooling.
  fetch: (input: Request) => fetch(input),
});

export type ApiClient = typeof apiClient;

/**
 * Refresh the Access_Token via `POST /auth/refresh` exactly once.
 *
 * Uses a **raw** `fetch` (not `apiClient`) so the refresh call itself bypasses
 * the auth middleware and can never recurse into another refresh.
 */
async function refreshAccessToken(): Promise<string | null> {
  const current = getToken();
  try {
    const response = await fetch(`${config.baseUrl}/auth/refresh`, {
      method: "POST",
      headers: current
        ? { Authorization: `Bearer ${current}`, "Content-Type": "application/json" }
        : { "Content-Type": "application/json" },
    });
    if (!response.ok) return null;
    const body = (await response.json()) as { access_token?: unknown };
    return typeof body.access_token === "string" ? body.access_token : null;
  } catch {
    return null;
  }
}

const authDeps: AuthMiddlewareDeps = {
  getToken,
  setToken,
  onUnauthenticated: handleUnauthenticated,
  refresh: refreshAccessToken,
};

apiClient.use(createAuthMiddleware(authDeps));
