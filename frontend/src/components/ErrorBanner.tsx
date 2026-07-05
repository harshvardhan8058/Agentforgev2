/**
 * `ErrorBanner`: uniform rendering of a normalized `ClientError` (Req 5.1, 5.2,
 * 5.5).
 *
 * Always presents `error.message`. For a `422 validation_error` it surfaces the
 * per-field messages; for other errors it surfaces relevant `details` fields
 * alongside the message. It never renders a stack trace (the normalizer already
 * strips internal text for `500`), and offers an optional retry affordance.
 */
import { AlertTriangle } from "lucide-react";

import type { ClientError } from "../api/errors";
import { cn } from "../lib/cn";
import { Button } from "./ui/Button";

function formatDetail(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function ErrorBanner({
  error,
  onRetry,
}: {
  error: ClientError;
  onRetry?: () => void;
}): JSX.Element {
  const detailEntries = Object.entries(error.details);
  const hasFieldErrors = error.fieldErrors && Object.keys(error.fieldErrors).length > 0;

  return (
    <div
      role="alert"
      className={cn(
        "error-banner flex flex-col gap-2 rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-text",
      )}
      data-testid="error-banner"
      data-kind={error.kind}
    >
      <p
        className="error-banner__message flex items-center gap-2 font-medium text-text"
        data-testid="error-message"
      >
        <AlertTriangle className="h-4 w-4 shrink-0 text-danger" aria-hidden="true" />
        {error.message}
      </p>

      {hasFieldErrors && (
        <ul
          className="error-banner__fields ml-6 list-disc text-text-muted"
          data-testid="error-field-errors"
        >
          {Object.entries(error.fieldErrors!).map(([field, message]) => (
            <li key={field} data-field={field}>
              <span className="error-banner__field-name font-medium text-text">
                {field}
              </span>
              : {message}
            </li>
          ))}
        </ul>
      )}

      {!hasFieldErrors && detailEntries.length > 0 && (
        <dl
          className="error-banner__details ml-6 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-text-muted"
          data-testid="error-details"
        >
          {detailEntries.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="font-medium text-text">{key}</dt>
              <dd className="font-mono text-xs">{formatDetail(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {onRetry && (
        <div className="mt-1">
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="error-banner__retry"
            onClick={onRetry}
          >
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}
