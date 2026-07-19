/**
 * `NotFoundView`: the in-shell 404 surface for unmatched protected routes.
 *
 * Rendered by the router's catch-all inside the authenticated `AppShell`, so
 * the Operator keeps their navigation and context while being told the
 * destination does not exist, with a clear path back to the dashboard.
 */
import { Link } from "react-router-dom";
import { Compass, ArrowLeft } from "lucide-react";

export function NotFoundView(): JSX.Element {
  return (
    <div
      className="flex min-h-[60vh] flex-col items-center justify-center gap-6 text-center"
      data-testid="not-found-view"
    >
      <span
        className="flex h-16 w-16 items-center justify-center rounded-2xl bg-primary-subtle text-primary"
        aria-hidden="true"
      >
        <Compass className="h-8 w-8" />
      </span>
      <div className="flex flex-col gap-2">
        <span className="text-sm font-semibold uppercase tracking-wide text-text-subtle">
          Error 404
        </span>
        <h1 className="text-3xl font-semibold tracking-tight text-text">
          This page wandered off
        </h1>
        <p className="mx-auto max-w-md text-sm text-text-muted">
          The page you&apos;re looking for doesn&apos;t exist or may have moved.
          Let&apos;s get you back to your workspace.
        </p>
      </div>
      <Link
        to="/"
        data-testid="not-found-home"
        className="inline-flex h-11 items-center gap-2 rounded-lg bg-primary px-5 text-sm font-medium text-primary-fg shadow-elevation-1 transition-colors hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-bg"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Back to dashboard
      </Link>
    </div>
  );
}
