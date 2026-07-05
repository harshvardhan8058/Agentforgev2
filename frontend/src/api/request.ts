/**
 * Thin bridge between the typed `apiClient` (openapi-fetch) and feature code /
 * React Query.
 *
 * `openapi-fetch` returns `{ data, error, response }` and only rejects on a
 * transport failure. `runRequest` collapses both failure modes into the single
 * normalized `ClientError` (via `mapError`, Property 5) that every feature
 * surfaces through `ErrorBanner`:
 *  - a non-2xx response → `mapError(response.status, error)` (the parsed
 *    AppError envelope, when present, is copied verbatim — so a cross-tenant
 *    `404` is presented as "not found" and never reveals another org, Req 4.7);
 *  - a transport/network failure → `mapError(null, undefined)` → `kind:
 *    "network"` (Req 5.6).
 *
 * On success it returns the typed `data` (or `undefined` for `204` responses),
 * so query/mutation functions can simply `await runRequest(() => apiClient...)`.
 */
import { mapError } from "./errors";

/** The shape every `openapi-fetch` call resolves to. */
interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

/**
 * Execute an `apiClient` call and return its typed data, or throw a normalized
 * `ClientError`. Never throws anything other than a `ClientError`.
 */
export async function runRequest<T>(
  op: () => Promise<FetchResult<T>>,
): Promise<T> {
  let result: FetchResult<T>;
  try {
    result = await op();
  } catch {
    // Transport-layer failure before any HTTP response was received (Req 5.6).
    throw mapError(null, undefined);
  }

  const { data, error, response } = result;
  if (!response.ok || error !== undefined) {
    throw mapError(response.status, error);
  }
  return data as T;
}
