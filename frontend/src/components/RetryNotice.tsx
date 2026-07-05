/**
 * `RetryNotice`: connectivity-error affordance offering a retry action (Req
 * 5.6). Used when a request fails at the network layer before any HTTP
 * response is received.
 */
export function RetryNotice({
  onRetry,
  message = "Unable to reach the server. Please check your connection and try again.",
}: {
  onRetry: () => void;
  message?: string;
}): JSX.Element {
  return (
    <div role="alert" className="retry-notice" data-testid="retry-notice">
      <p className="retry-notice__message">{message}</p>
      <button type="button" className="retry-notice__retry" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}
