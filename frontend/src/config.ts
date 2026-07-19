/**
 * Web_Client configuration.
 *
 * The Backend_API base URL is resolved from a **runtime** source first
 * (`window.__AGENTFORGE_CONFIG__.apiBaseUrl`, injected at container start by the
 * Frontend_Image entrypoint, deployment Req 8.1-8.4), then the build-time
 * `import.meta.env.VITE_API_BASE_URL`, then the documented default. This lets one
 * build-once image run anywhere without a rebuild. No credential or secret value
 * is ever read here or embedded in the compiled bundle — the surface is restricted
 * to the non-secret base URL and non-secret feature flags (Req 1.5, deployment
 * Req 8.5). Under jsdom (no `window.__AGENTFORGE_CONFIG__`) resolution is identical
 * to the previous build-time-only behavior.
 */

/** Non-secret client configuration. */
export interface AppConfig {
  /** Backend_API base URL that every API_Client call targets. */
  readonly baseUrl: string;
  /** Non-secret feature flags (safe to embed in the bundle). */
  readonly flags: Readonly<Record<string, boolean>>;
}

/**
 * The subset of the Vite environment the client reads. Deliberately narrow: the
 * only recognized key is the non-secret Backend_API base URL (Req 1.4, 1.5).
 */
export type ConfigEnv = { readonly VITE_API_BASE_URL?: string };

const DEFAULT_BASE_URL = "http://localhost:8000";

/**
 * Resolve the effective Backend_API base:
 *
 *  - `"/"` (or any value that is only slashes) → **same-origin**: an empty base
 *    so the API_Client issues **relative** requests against the exact origin
 *    that served the SPA. This is the correct mode behind a same-origin reverse
 *    proxy (the bundled nginx) and works from ANY host — `localhost`,
 *    `127.0.0.1`, a LAN IP, or a domain, over http or https — with no CORS. It
 *    is the compose default, and is what prevents the "Unable to reach the
 *    server" failure that a hardcoded `http://localhost` causes when the app is
 *    opened from a different origin.
 *  - a non-empty absolute URL → used verbatim (trailing slash trimmed), for
 *    deployments where the API lives on a separate origin (CORS then applies).
 *  - unset/empty → the documented dev default (`http://localhost:8000`), so
 *    `npm run dev` targets a local backend with no configuration.
 */
function normalizeBaseUrl(raw: string | undefined): string {
  const value = (raw ?? "").trim();
  if (value.length === 0) return DEFAULT_BASE_URL;
  // Same-origin: a bare "/" (or "///") means "relative to the serving origin".
  if (/^\/+$/.test(value)) return "";
  return value.endsWith("/") ? value.slice(0, -1) : value;
}

/** Shape of the runtime config global injected by the container entrypoint. */
type RuntimeConfig = { readonly apiBaseUrl?: string };

/**
 * Read the runtime Backend_API base URL injected at container start via
 * `/config.js` (`window.__AGENTFORGE_CONFIG__.apiBaseUrl`). Returns `undefined`
 * when there is no `window` (e.g. jsdom/tests, SSR) or no runtime value, so the
 * resolver falls through to the build-time value and then the default. This adds
 * only a non-secret base-URL source — no secret path (deployment Req 8.5).
 */
function runtimeBaseUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as unknown as { __AGENTFORGE_CONFIG__?: RuntimeConfig })
    .__AGENTFORGE_CONFIG__?.apiBaseUrl;
}

/**
 * Resolve configuration, preferring the runtime value, then the build-time Vite
 * environment, then the documented default. Only the base URL and non-secret
 * flags are exposed; there is intentionally no code path that reads a secret.
 */
export function resolveConfig(env: ConfigEnv = import.meta.env): AppConfig {
  return {
    baseUrl: normalizeBaseUrl(runtimeBaseUrl() ?? env.VITE_API_BASE_URL),
    flags: {},
  };
}

/** The resolved singleton configuration for the running application. */
export const config: AppConfig = resolveConfig();
