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
 * No middleware is attached yet — the bearer-attach + 401 refresh-once-then-retry
 * middleware is added in a later task. No secret is embedded; only the base URL
 * from `import.meta.env` is used (Req 1.5).
 */
import createClient from "openapi-fetch";

import { config } from "../config";
import type { paths } from "./schema";

/** The typed API_Client. All feature code imports this single instance. */
export const apiClient = createClient<paths>({
  baseUrl: config.baseUrl,
});

export type ApiClient = typeof apiClient;
