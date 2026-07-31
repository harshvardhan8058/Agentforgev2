/**
 * The single, total AppError-envelope normalizer (Property 5).
 *
 * Every non-2xx Backend_API response and every network-layer failure flows
 * through `mapError`, producing one uniform `ClientError` that feature code
 * renders via `ErrorBanner`. `mapError` is **total**: for any status (including
 * the network case, represented as `null`) and any body (valid envelope,
 * partial, garbage, or none) it returns a defined `ClientError` with a
 * non-empty, user-presentable message and never throws.
 */

/** The coarse category a `ClientError` is bucketed into for UI behavior. */
export type ErrorKind =
  | "auth"
  | "forbidden"
  | "not_found"
  | "validation"
  | "rate_limited"
  | "provider"
  | "server"
  | "network"
  | "unknown";

/** The normalized, user-presentable error shape all features consume. */
export interface ClientError {
  code: string;
  message: string;
  status: number | null;
  details: Record<string, unknown>;
  kind: ErrorKind;
  /** Populated for 422 validation_error (and 400 field validation). */
  fieldErrors?: Record<string, string>;
}

interface Envelope {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Extract a well-formed AppError envelope, or `null` if the body is not one. */
function extractEnvelope(body: unknown): Envelope | null {
  if (!isPlainObject(body)) return null;
  const err = body.error;
  if (!isPlainObject(err)) return null;
  if (typeof err.code !== "string") return null;
  if (typeof err.message !== "string") return null;
  const details = isPlainObject(err.details) ? err.details : {};
  return { code: err.code, message: err.message, details };
}

/** Derive the coarse `kind` from the HTTP status (and code for 400). */
function kindFor(status: number | null, code: string | null): ErrorKind {
  if (status === null) return "network";
  switch (status) {
    case 401:
      return "auth";
    case 403:
      return "forbidden";
    case 404:
      return "not_found";
    case 422:
      return "validation";
    case 429:
      return "rate_limited";
    case 502:
      return "provider";
    case 400:
      // 400 covers guardrail_blocked / missing_variable / empty_document /
      // field validation, plus the domain-rule refusals the admin surface can
      // return (`last_owner`, `org_mismatch`, and the uniqueness conflicts) —
      // all "the request as submitted cannot be applied", i.e. validation-class.
      // Unknown 400s fall back to "unknown".
      return code &&
        [
          "guardrail_blocked",
          "missing_variable",
          "empty_document",
          "validation_error",
          "last_owner",
          "org_mismatch",
          "email_exists",
          "membership_exists",
          "team_exists",
        ].includes(code)
        ? "validation"
        : "unknown";
    default:
      if (status >= 500) return "server";
      return "unknown";
  }
}

/** A generic, user-presentable fallback message when no envelope message exists. */
function genericMessage(kind: ErrorKind, status: number | null): string {
  switch (kind) {
    case "network":
      return "Unable to reach the server. Please check your connection and try again.";
    case "auth":
      return "Your session is no longer valid. Please sign in again.";
    case "forbidden":
      return "You do not have permission to perform this action.";
    case "not_found":
      return "The requested resource was not found.";
    case "validation":
      return "The request could not be processed as submitted.";
    case "rate_limited":
      return "Too many requests. Please wait a moment and try again.";
    case "provider":
      return "The upstream provider returned an error. Please try again.";
    case "server":
      return "An internal error occurred while processing the request.";
    default:
      return status === null
        ? "An unexpected error occurred."
        : `The request failed with status ${status}.`;
  }
}

/** A synthetic error code when the body carries no envelope code. */
function syntheticCode(status: number | null): string {
  if (status === null) return "network";
  if (status >= 500) return "internal_error";
  return "http_error";
}

/**
 * Build `fieldErrors` from a validation envelope's details.
 *
 * Handles the 422 `details.errors` list (FastAPI `exc.errors()` shape:
 * `{ loc: [...], msg }`) and the 400 `details.field` single-field shape.
 */
function fieldErrorsFrom(details: Record<string, unknown>): Record<string, string> | undefined {
  const out: Record<string, string> = {};

  const errors = details.errors;
  if (Array.isArray(errors)) {
    for (const entry of errors) {
      if (!isPlainObject(entry)) continue;
      const loc = entry.loc;
      const msg = typeof entry.msg === "string" ? entry.msg : "Invalid value";
      let field = "";
      if (Array.isArray(loc)) {
        // Use the last string location segment as the field name, skipping the
        // conventional "body" prefix.
        const segments = loc.filter(
          (s): s is string => typeof s === "string" && s !== "body",
        );
        field = segments.length > 0 ? segments[segments.length - 1] : "";
      }
      if (field.length === 0) field = "_";
      out[field] = msg;
    }
  }

  if (typeof details.field === "string") {
    const msg =
      typeof details.message === "string" && details.message.trim().length > 0
        ? details.message
        : "Invalid value";
    out[details.field] = msg;
  }

  return Object.keys(out).length > 0 ? out : undefined;
}

/**
 * Normalize any (status, body) pair — or a network failure (`status = null`) —
 * into a defined `ClientError`. Total and never throws (Property 5).
 */
export function mapError(status: number | null, body: unknown): ClientError {
  const envelope = extractEnvelope(body);
  const kind = kindFor(status, envelope?.code ?? null);

  const details = envelope?.details ?? {};
  const code =
    envelope?.code && envelope.code.trim().length > 0
      ? envelope.code
      : syntheticCode(status);

  const envMessage = envelope?.message;
  const message =
    typeof envMessage === "string" && envMessage.trim().length > 0
      ? envMessage
      : genericMessage(kind, status);

  const error: ClientError = { code, message, status, details, kind };

  if (kind === "validation") {
    const fieldErrors = fieldErrorsFrom(details);
    if (fieldErrors) error.fieldErrors = fieldErrors;
  }

  return error;
}
