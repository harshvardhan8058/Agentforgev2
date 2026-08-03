/**
 * Shared E2E helpers: keyless auth seeding + deterministic Backend_API mocking.
 *
 * Auth: the frontend derives its Session by DECODING (not verifying) the JWT
 * claims client-side, so a test can seed a well-formed, unsigned token into the
 * same `localStorage` key the app reads (`agentforge.token`) and land in an
 * authenticated session — no backend and no real credential.
 *
 * API: every backend call targets `http://localhost:8000` (the build-time
 * default). That origin is cross-origin to the preview server, so mocking it
 * with `page.route` never intercepts the app's own HTML/JS/CSS. A catch-all
 * keeps unrelated calls from erroring; specs register specific routes which,
 * per Playwright's last-registered-wins matching, take precedence.
 */
import type { Page, Route } from "@playwright/test";

export const API = "http://localhost:8000";
export const TOKEN_STORAGE_KEY = "agentforge.token";
export const ORG_TOKENS_STORAGE_KEY = "agentforge.orgTokens";

export type Role = "owner" | "admin" | "member" | "viewer";

function base64url(input: string): string {
  return Buffer.from(input, "utf-8").toString("base64url");
}

/**
 * Build a well-formed, UNSIGNED JWT carrying the four claims the Session reads.
 * The signature segment is inert filler — the client never verifies it.
 */
export function makeJwt(options: {
  role?: Role;
  orgId?: string;
  sub?: string;
  /** Seconds from now until expiry (default: +1 year). */
  ttlSeconds?: number;
} = {}): string {
  const {
    role = "owner",
    orgId = "11111111-1111-4111-8111-111111111111",
    sub = "22222222-2222-4222-8222-222222222222",
    ttlSeconds = 60 * 60 * 24 * 365,
  } = options;
  const exp = Math.floor(Date.now() / 1000) + ttlSeconds;
  const header = base64url(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const payload = base64url(JSON.stringify({ sub, org_id: orgId, role, exp }));
  return `${header}.${payload}.e2e-signature`;
}

/**
 * Seed an authenticated Session before the app boots. Sets the token (and the
 * org-token map that backs the org switcher) into `localStorage` via an init
 * script that runs before any page script on every navigation.
 */
export async function seedAuth(
  page: Page,
  options: { role?: Role; orgId?: string } = {},
): Promise<string> {
  const token = makeJwt(options);
  const orgId = options.orgId ?? "11111111-1111-4111-8111-111111111111";
  await page.addInitScript(
    ([tokenKey, orgKey, tok, org]) => {
      try {
        localStorage.setItem(tokenKey, tok);
        localStorage.setItem(orgKey, JSON.stringify({ [org]: tok }));
      } catch {
        /* storage unavailable — the app falls back to unauthenticated */
      }
    },
    [TOKEN_STORAGE_KEY, ORG_TOKENS_STORAGE_KEY, token, orgId] as const,
  );
  return token;
}

/**
 * The API is served cross-origin (`:8000`) relative to the preview app
 * (`:4173`), so mocked responses must carry CORS headers and preflight
 * `OPTIONS` must be answered, exactly as a real cross-origin API would.
 */
const CORS_HEADERS: Record<string, string> = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
  "access-control-allow-headers": "authorization,content-type",
};

/**
 * Fulfill a route: answer CORS preflight `OPTIONS` with 204, otherwise return
 * `body` as JSON with CORS headers so the cross-origin app can read it. A `204`
 * status yields an empty body (used by DELETE).
 */
export function respond(route: Route, body: unknown, status = 200): Promise<void> {
  if (route.request().method() === "OPTIONS") {
    return route.fulfill({ status: 204, headers: CORS_HEADERS });
  }
  if (status === 204) {
    return route.fulfill({ status, headers: CORS_HEADERS });
  }
  return route.fulfill({
    status,
    headers: { ...CORS_HEADERS, "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

/**
 * Install baseline API mocks: a healthy readiness probe, a refresh endpoint
 * (so a stray 401 never triggers a real refresh), and a catch-all returning an
 * empty object so any unmocked GET renders an empty/loaded state rather than a
 * network error, plus global CORS-preflight handling. Specs override specific
 * routes on top of this (last-registered route wins).
 */
export async function mockCommon(page: Page): Promise<void> {
  // Catch-all for the API origin ONLY (never the preview app's own assets).
  await page.route(`${API}/**`, (route) => respond(route, {}));

  await page.route(`${API}/health/ready`, (route) =>
    respond(route, { status: "ready", dependencies: { database: "up", redis: "up" } }),
  );
  await page.route(`${API}/auth/refresh`, (route) =>
    respond(route, { access_token: makeJwt(), token_type: "bearer" }),
  );

  // Collection endpoints fetched on mount answer with an ARRAY. The catch-all's
  // `{}` is fine for a view that reads object fields, but a list renderer would
  // be handed a non-iterable — a mock artefact, not a product defect. Declaring
  // the real shape here keeps the sweep honest for every view that lists.
  await page.route(`${API}/orgs/*/members`, (route) => respond(route, []));
  await page.route(`${API}/orgs/*/teams`, (route) => respond(route, []));
  await page.route(`${API}/orgs/*/api-keys`, (route) => respond(route, []));
  await page.route(`${API}/integrations/connections`, (route) => respond(route, []));
  // The audit log is a collection endpoint like the others; `{}` would be handed to a table.
  await page.route(`${API}/audit-events**`, (route) => respond(route, []));
  // Webhook subscriptions and each subscription's delivery log are both collections.
  await page.route(`${API}/webhooks`, (route) => respond(route, []));
  await page.route(`${API}/webhooks/*/deliveries**`, (route) => respond(route, []));
  // The analytics page reads the org's spend standing; `{}` would render as absent numbers.
  await page.route(`${API}/budget`, (route) =>
    respond(route, {
      period_start: "2026-08-01T00:00:00Z",
      period_end: "2026-09-01T00:00:00Z",
      spent: "0",
      limit_amount: null,
      remaining: null,
      percent_used: null,
      action: null,
      exceeded: false,
      blocked: false,
    }),
  );

  // Trace surfaces ask whether this deployment exports traces anywhere. The catch-all's
  // `{}` would leave the notice unable to render either state, so the keyless shape is
  // declared here.
  await page.route(`${API}/observability/status`, (route) =>
    respond(route, {
      trace_export: { enabled: false, exporter: "noop", destination: null },
    }),
  );

  // The analytics page always asks how the deployment is priced. The catch-all's
  // `{}` would render as absent rates rather than as the honest "prices nothing"
  // state, so the real unpriced shape is declared here.
  await page.route(`${API}/analytics/cost-rates`, (route) =>
    respond(route, {
      preset: null,
      available_presets: ["groq-public-2026-07"],
      default_prompt_per_1k: "0.0",
      default_completion_per_1k: "0.0",
      configured: false,
      rates: [],
    }),
  );
}

/** Register a JSON responder for a specific API path (any method). */
export async function mockJson(
  page: Page,
  path: string,
  body: unknown,
  status = 200,
): Promise<void> {
  await page.route(`${API}${path}`, (route) => respond(route, body, status));
}
