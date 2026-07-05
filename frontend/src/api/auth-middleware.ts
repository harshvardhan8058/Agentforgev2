/**
 * API_Client auth middleware: request-side bearer attach + response-side 401
 * refresh-once-then-retry (Properties 7 and 6).
 *
 * Request side (Req 2.6): when a token is stored, attach
 * `Authorization: Bearer <token>` on every authenticated request; the public
 * auth endpoints (`/auth/login`, `/auth/register-self`) never receive it, and
 * no token means no header.
 *
 * Response side (Req 3.3, 3.5, 3.6): on a `401` for an authenticated request,
 * call `POST /auth/refresh` **exactly once**; on success replace the stored
 * token and retry the original request once; on refresh failure or a second
 * `401`, clear the token and route to `/login`. A per-original-request flag
 * guarantees the policy can never loop (Property 6).
 */
import type { Middleware } from "openapi-fetch";

/** Endpoints that must never carry the bearer header. */
export const PUBLIC_AUTH_PATHS: ReadonlySet<string> = new Set([
  "/auth/login",
  "/auth/register-self",
]);

/** True iff `path` is a public (unauthenticated) auth endpoint. */
export function isPublicAuthPath(path: string): boolean {
  return PUBLIC_AUTH_PATHS.has(path);
}

/**
 * The `Authorization` header value to attach for `path`, or `null` when none
 * should be attached (public auth path, or no valid token). Pure (Property 7).
 */
export function authorizationFor(path: string, token: string | null): string | null {
  if (isPublicAuthPath(path)) return null;
  if (typeof token !== "string" || token.length === 0) return null;
  return `Bearer ${token}`;
}

/** Dependencies the middleware needs, injected at wiring time. */
export interface AuthMiddlewareDeps {
  getToken(): string | null;
  setToken(token: string): void;
  /** Clear the session + route to `/login`. */
  onUnauthenticated(): void;
  /** Call `POST /auth/refresh` once; resolve to a new token or `null`. */
  refresh(): Promise<string | null>;
}

/** The result of running the bounded refresh policy. */
export interface RefreshPolicyResult {
  finalStatus: number;
  attempts: number;
  refreshCalls: number;
  cleared: boolean;
}

/** Hooks driving the abstract, testable refresh policy. */
export interface RefreshPolicyHooks {
  /** Issue an attempt of the original request with the given token; yield status. */
  send(token: string | null): Promise<number>;
  /** Attempt a single token refresh; yield a new token or `null`. */
  refresh(): Promise<string | null>;
  /** Invoked when the session must be cleared + routed to login. */
  onCleared(): void;
  /** The token to use for the first attempt. */
  initialToken(): string | null;
}

/**
 * The canonical bounded 401 policy (Property 6): at most one refresh and at most
 * two original-request attempts, so it can never loop. The middleware below
 * implements the same bound over the openapi-fetch hooks.
 */
export async function executeWithRefreshPolicy(
  hooks: RefreshPolicyHooks,
): Promise<RefreshPolicyResult> {
  let attempts = 0;
  let refreshCalls = 0;

  const first = await hooks.send(hooks.initialToken());
  attempts += 1;
  if (first !== 401) {
    return { finalStatus: first, attempts, refreshCalls, cleared: false };
  }

  // Single refresh attempt.
  refreshCalls += 1;
  const newToken = await hooks.refresh();
  if (newToken === null) {
    hooks.onCleared();
    return { finalStatus: 401, attempts, refreshCalls, cleared: true };
  }

  // Single retry with the refreshed token.
  const second = await hooks.send(newToken);
  attempts += 1;
  if (second === 401) {
    hooks.onCleared();
    return { finalStatus: 401, attempts, refreshCalls, cleared: true };
  }
  return { finalStatus: second, attempts, refreshCalls, cleared: false };
}

/**
 * Build the openapi-fetch middleware. Uses a `WeakSet` keyed by the original
 * `Request` so a retried request can never itself trigger another refresh.
 */
export function createAuthMiddleware(deps: AuthMiddlewareDeps): Middleware {
  const retried = new WeakSet<Request>();

  return {
    onRequest({ request, schemaPath }) {
      const header = authorizationFor(schemaPath, deps.getToken());
      if (header) request.headers.set("Authorization", header);
      return request;
    },

    async onResponse({ request, response, schemaPath }) {
      if (response.status !== 401) return response;
      if (isPublicAuthPath(schemaPath)) return response;
      // Per-original-request guard: never refresh/retry more than once.
      if (retried.has(request)) {
        return response;
      }
      retried.add(request);

      const newToken = await deps.refresh();
      if (newToken === null) {
        deps.onUnauthenticated();
        return response;
      }
      deps.setToken(newToken);

      const retryRequest = request.clone();
      retryRequest.headers.set("Authorization", `Bearer ${newToken}`);
      const retryResponse = await fetch(retryRequest);
      if (retryResponse.status === 401) {
        deps.onUnauthenticated();
      }
      return retryResponse;
    },
  };
}
