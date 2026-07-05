/**
 * `ErrorBanner`: uniform rendering of a normalized `ClientError` (Req 5.1, 5.2,
 * 5.5).
 *
 * Always presents `error.message`. For a `422 validation_error` it surfaces the
 * per-field messages; for other errors it surfaces relevant `details` fields
 * alongside the message. It never renders a stack trace (the normalizer already
 * strips internal text for `500`), and offers an optional retry affordance.
 */
import type { ClientError } from "../api/errors";

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
      className="error-banner"
      data-testid="error-banner"
      data-kind={error.kind}
    >
      <p className="error-banner__message" data-testid="error-message">
        {error.message}
      </p>

      {hasFieldErrors && (
        <ul className="error-banner__fields" data-testid="error-field-errors">
          {Object.entries(error.fieldErrors!).map(([field, message]) => (
            <li key={field} data-field={field}>
              <span className="error-banner__field-name">{field}</span>: {message}
            </li>
          ))}
        </ul>
      )}

      {!hasFieldErrors && detailEntries.length > 0 && (
        <dl className="error-banner__details" data-testid="error-details">
          {detailEntries.map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{formatDetail(value)}</dd>
            </div>
          ))}
        </dl>
      )}

      {onRetry && (
        <button type="button" className="error-banner__retry" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}
