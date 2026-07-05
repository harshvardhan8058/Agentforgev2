/**
 * `BreakdownBoundary`: per-breakdown error isolation (Req 11.6).
 *
 * Wraps a single usage breakdown so that if rendering it fails, the failure is
 * caught and a compact fallback is shown **for that breakdown only** — the
 * usage totals and the other breakdowns keep rendering.
 */
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  /** Stable id used for the fallback test hook. */
  group: string;
  label: string;
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export class BreakdownBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  // Swallow the error (already isolated); nothing to report upstream.
  componentDidCatch(_error: Error, _info: ErrorInfo): void {}

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div
          className="rounded-lg border border-dashed border-border bg-bg-subtle p-4 text-sm text-text-muted"
          data-testid={`breakdown-error-${this.props.group}`}
          role="status"
        >
          The “{this.props.label}” breakdown is unavailable.
        </div>
      );
    }
    return this.props.children;
  }
}
