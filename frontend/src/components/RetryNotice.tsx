/**
 * `RetryNotice`: connectivity-error affordance offering a retry action (Req
 * 5.6). Used when a request fails at the network layer before any HTTP
 * response is received.
 */
import type { JSX } from "react";
import { WifiOff } from "lucide-react";

import { Button } from "./ui/Button";

export function RetryNotice({
  onRetry,
  message = "Unable to reach the server. Please check your connection and try again.",
}: {
  onRetry: () => void;
  message?: string;
}): JSX.Element {
  return (
    <div
      role="alert"
      className="retry-notice flex flex-col items-start gap-3 rounded-lg border border-border bg-surface p-4 text-sm"
      data-testid="retry-notice"
    >
      <p className="retry-notice__message flex items-center gap-2 text-text">
        <WifiOff className="h-4 w-4 shrink-0 text-warning" aria-hidden="true" />
        {message}
      </p>
      <Button
        type="button"
        variant="secondary"
        size="sm"
        className="retry-notice__retry"
        onClick={onRetry}
      >
        Retry
      </Button>
    </div>
  );
}
