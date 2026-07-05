/**
 * Web_Client configuration.
 *
 * The Backend_API base URL is read **exclusively** from
 * `import.meta.env.VITE_API_BASE_URL` (Req 1.4). No credential or secret value
 * is ever read here or embedded in the compiled bundle — the surface is
 * restricted to the base URL and non-secret feature flags (Req 1.5).
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

/** Trim a trailing slash so path joins are unambiguous. */
function normalizeBaseUrl(raw: string | undefined): string {
  const value = (raw ?? "").trim();
  const resolved = value.length > 0 ? value : DEFAULT_BASE_URL;
  return resolved.endsWith("/") ? resolved.slice(0, -1) : resolved;
}

/**
 * Resolve configuration from the Vite environment. Only the base URL and
 * non-secret flags are exposed; there is intentionally no code path that reads
 * a secret.
 */
export function resolveConfig(env: ConfigEnv = import.meta.env): AppConfig {
  return {
    baseUrl: normalizeBaseUrl(env.VITE_API_BASE_URL),
    flags: {},
  };
}

/** The resolved singleton configuration for the running application. */
export const config: AppConfig = resolveConfig();
