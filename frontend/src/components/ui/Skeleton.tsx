/**
 * `Skeleton`: a shimmer placeholder that matches the final layout while data
 * loads. Marked `aria-hidden` and exposed with a stable test id.
 */
import type { JSX } from "react";
import { type HTMLAttributes } from "react";

import { cn } from "../../lib/cn";

export function Skeleton({
  className,
  ...rest
}: HTMLAttributes<HTMLDivElement>): JSX.Element {
  return (
    <div
      aria-hidden="true"
      data-testid="skeleton"
      className={cn(
        "animate-pulse rounded-md bg-surface-raised",
        className,
      )}
      {...rest}
    />
  );
}
