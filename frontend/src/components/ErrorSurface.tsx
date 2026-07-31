/**
 * `ErrorSurface`: the single cross-cutting dispatcher that renders a normalized
 * `ClientError` with the status-specific behavior from the design's Error
 * Handling table.
 *
 * A network-layer failure (`kind === "network"`, produced by `mapError(null, …)`)
 * is a connectivity problem, so it is surfaced through `RetryNotice` — a
 * connectivity message plus a retry affordance (Req 5.6). Every other error
 * (envelope-backed: `422` field errors, `429` rate-limit, `500` generic
 * no-stack, `502` provider, `404` not-found, `400 guardrail_blocked` /
 * `missing_variable`, document errors, `409`, …) is surfaced uniformly through
 * `ErrorBanner`, which already renders `message` + relevant `details` /
 * `fieldErrors` without any stack text.
 *
 * Because the submitting form keeps its input state independent of the request
 * lifecycle, surfacing an error here never clears the Operator's input — so
 * `429`, `502`, and `guardrail_blocked` retries need no re-entry (Req 5.4, 6.5,
 * 7.5).
 */
import type { JSX } from "react";
import type { ClientError } from "../api/errors";
import { ErrorBanner } from "./ErrorBanner";
import { RetryNotice } from "./RetryNotice";

export function ErrorSurface({
  error,
  onRetry,
}: {
  error: ClientError;
  /** Re-attempt the failed operation (re-submit a mutation, refetch a query). */
  onRetry?: () => void;
}): JSX.Element {
  // Connectivity failure before any HTTP response → connectivity error + retry.
  if (error.kind === "network" && onRetry) {
    return <RetryNotice onRetry={onRetry} message={error.message} />;
  }
  return <ErrorBanner error={error} onRetry={onRetry} />;
}
