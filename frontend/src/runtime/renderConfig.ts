/**
 * Canonical render logic for the Frontend_Image runtime `config.js`
 * (Runtime_Config, deployment Req 8.1-8.5).
 *
 * This mirrors exactly what `frontend/docker/entrypoint.sh` produces via
 * `envsubst` at container start:
 *   - when API_BASE_URL is set   -> `window.__AGENTFORGE_CONFIG__ = { apiBaseUrl: "<value>" };`
 *   - when API_BASE_URL is unset -> `window.__AGENTFORGE_CONFIG__ = {};`
 *
 * It is intentionally NOT imported by the application bundle — the app reads the
 * resulting `window.__AGENTFORGE_CONFIG__` global through `resolveConfig()`.
 * Keeping the render contract here lets the build-once/run-anywhere property
 * (Property 4) be verified without building a container image. It reads/writes
 * only the non-secret base URL — there is no secret path (Req 8.5).
 */

/** The `envsubst` template rendered when API_BASE_URL is provided. */
export const CONFIG_JS_TEMPLATE =
  'window.__AGENTFORGE_CONFIG__ = { apiBaseUrl: "${API_BASE_URL}" };\n';

/** Rendered output when no API_BASE_URL is supplied (empty object -> app default). */
export const EMPTY_CONFIG_JS = "window.__AGENTFORGE_CONFIG__ = {};\n";

/**
 * Render the runtime `config.js` for a given `API_BASE_URL`. When the value is
 * `undefined`/`null`/empty, an empty config object is emitted so the Web_Client
 * falls back to its documented default (Req 8.4).
 */
export function renderConfigJs(apiBaseUrl?: string | null): string {
  if (apiBaseUrl === undefined || apiBaseUrl === null || apiBaseUrl === "") {
    return EMPTY_CONFIG_JS;
  }
  // Use a replacer function so `$`-sequences in the value are inserted literally
  // (matching envsubst, which only expands the named variable).
  return CONFIG_JS_TEMPLATE.replace("${API_BASE_URL}", () => apiBaseUrl);
}
