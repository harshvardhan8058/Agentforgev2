/**
 * `PageFallback`: the Suspense fallback shown while a lazily-loaded route
 * chunk is fetched. A lightweight, layout-matching skeleton (header + content
 * blocks) so route transitions never flash empty. Decorative and aria-hidden.
 */
import type { JSX } from "react";
import { Skeleton } from "../components/ui/Skeleton";

export function PageFallback(): JSX.Element {
  return (
    <div
      className="flex flex-col gap-6"
      data-testid="page-fallback"
      aria-busy="true"
      aria-live="polite"
    >
      <span className="sr-only">Loading…</span>
      <div className="flex flex-col gap-2 border-b border-border pb-5">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-4 w-80 max-w-full" />
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-28 w-full" />
        ))}
      </div>
    </div>
  );
}
